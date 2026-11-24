"""The Places view's data: towns to settle, days with no position, and your known places.

  GET /api/places   questions  each known place make places couldn't settle: its row, why (several
                               places match, none does, or the country isn't known), the options with
                               their distance from the GPS points around its dates, and those points
                    gaps       each run of days with nothing to say where you were: no ride, no photo
                               with GPS and no stay. With the known places you've given for its days
                               (so a filled gap stays in the list, marked), the days still open, the
                               photos and diary entries
                               of those days and the two either side (each with its day), which may
                               say, and the last position before it and the first after
                    known      every row of manual/known_places.csv, with its looked-up position
"""
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from pathlib import Path

from common.tables import read_json, read_rows
from repo import LOCATED, PLACE_QUESTIONS, PLACES_CSV, TRACK_POINTS
from settings import settings
from shared import cached
from store import rows


def day_range(first, last):
    """Each ISO day from first to last (or first alone): none if either isn't a date."""
    try:
        d, end = date.fromisoformat(first), date.fromisoformat(last or first)
    except ValueError:
        return []
    return [(d + timedelta(days=i)).isoformat() for i in range((end - d).days + 1)]


def covered_days():
    """Local days a ride, a GPS photo or a stay says where you were (UTC days for the track, close enough).
    Known places aren't counted: a gap they fill stays a gap, shown as filled."""
    def load():
        days = {r["utc"][:10] for r in read_rows(TRACK_POINTS)}
        days |= {r["local_date"] for r in read_rows(LOCATED / "photos.csv") if r["position_source"] == "photo_gps"}
        return days
    days = set(cached([TRACK_POINTS, LOCATED / "photos.csv"], load))
    for s in rows("stays"):
        days.update(day_range(s["first_night"], s["leaving"]))
    return days


def positions():
    """Every (local day, lat, lon, what) something places you at, sorted by day: rides, GPS photos, known points."""
    def load():
        out = [(r["utc"][:10], float(r["lat"]), float(r["lon"]), "ride") for r in read_rows(TRACK_POINTS)]
        out += [(r["local_date"], float(r["lat"]), float(r["lon"]), "photo") for r in read_rows(LOCATED / "photos.csv")
                if r["position_source"] == "photo_gps" and r["lat"]]
        out += [(r["end_date"] or r["start_date"], float(r["lat"]), float(r["lon"]), r["town"] or "known place")
                for r in read_rows(PLACES_CSV) if r["lat"]]
        out.sort(key=lambda p: p[0])
        return out
    return cached([TRACK_POINTS, LOCATED / "photos.csv", PLACES_CSV], load)


AROUND = 2   # days either side of a gap whose photos and entries come with it


def gaps():
    covered = covered_days()
    looked_up = {r["id"]: r for r in read_rows(PLACES_CSV)}
    mine = []
    for r in rows("known_places"):
        f = looked_up.get(r["id"], {})
        lat, lon = (r["lat"], r["lon"]) if r["lat"] else (f.get("lat", ""), f.get("lon", ""))
        mine.append({"id": r["id"], "days": set(day_range(r["start_date"], r["end_date"])),
                     "start_date": r["start_date"], "end_date": r["end_date"], "town": r["town"], "country": r["country"],
                     "note": r["note"], "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
                     "how": "your point" if r["lat"] else "looked up" if lat else "looked up on rebuild"})
    known = positions()
    days_of = [p[0] for p in known]
    entries = {}
    for name in ("audio", "written", "blog"):
        for r in read_rows(LOCATED / f"{name}.csv"):
            if r["local_date"]:
                entries.setdefault(r["local_date"], []).append({"day": r["local_date"], "kind": r.get("kind") or name, "file": r["file"],
                                                                "stem": Path(r["file"]).stem, "words": r["words"],
                                                                "utc": r["utc"]})
    photos = {}
    for r in read_rows(LOCATED / "photos.csv"):
        photos.setdefault(r["local_date"], []).append({"day": r["local_date"], "file": r["file"], "name": Path(r["file"]).name,
                                                       "position": r["position_source"], "lat": r["lat"], "lon": r["lon"]})
    runs, d = [], settings.trip.start
    while d <= settings.trip.end:
        if d.isoformat() not in covered:
            if runs and runs[-1][1] == d - timedelta(days=1):
                runs[-1][1] = d
            else:
                runs.append([d, d])
        d += timedelta(days=1)
    out = []
    for first, last in runs:
        days = [(first + timedelta(days=i)).isoformat() for i in range(-AROUND, (last - first).days + 1 + AROUND)]
        i, j = bisect_left(days_of, first.isoformat()), bisect_right(days_of, last.isoformat())
        side = lambda p: {"day": p[0], "lat": p[1], "lon": p[2], "what": p[3]} if p else None
        own = set(day_range(first.isoformat(), last.isoformat()))
        filled = [{k: v for k, v in m.items() if k != "days"} for m in mine if m["days"] & own]
        open_days = sorted(own - set().union(*(m["days"] for m in mine if m["days"] & own)))
        out.append({"key": f"gap:{first}", "first": first.isoformat(), "last": last.isoformat(),
                    "days": len(own), "known": filled, "open": open_days,
                    "status": "filled" if not open_days else "partly" if filled else "open",
                    "entries": [e for d in days for e in entries.get(d, [])],
                    "photos": [p for d in days for p in photos.get(d, [])][:120],
                    "before": side(known[i - 1] if i else None), "after": side(known[j] if j < len(known) else None)})
    return out


def places():
    looked_up = {r["id"]: r for r in read_rows(PLACES_CSV)}
    known = [{**r, "found": {k: looked_up[r["id"]].get(k, "") for k in ("lat", "lon", "geoname", "feature", "region")}
              if r["id"] in looked_up else None} for r in rows("known_places")]
    questions = read_json(PLACE_QUESTIONS, [])
    picks = {(p["town"].lower(), p["country"]) for p in rows("place_picks")}
    for q in questions:
        q["answered"] = (q["row"]["town"].lower(), q["country_code"]) in picks
    return {"questions": questions, "gaps": gaps(), "known": known}


def handle(method, parts, query, body):
    if method == "GET" and parts == []:
        return places()
    return None
