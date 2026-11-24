"""The Places view's data: towns to settle, days with no position, and your known places.

  GET /api/places   questions  each known place make places couldn't settle: its row, why (several
                               places match, none does, or the country isn't known), the options with
                               their distance from the GPS points around its dates, and those points
                    gaps       each run of days with nothing to say where you were: no ride, no photo
                               with GPS, no known place and no stay. With the photos and diary entries
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


def covered_days():
    """Local days something says where you were (UTC days for the track, which is close enough)."""
    def load():
        days = {r["utc"][:10] for r in read_rows(TRACK_POINTS)}
        days |= {r["local_date"] for r in read_rows(LOCATED / "photos.csv") if r["position_source"] == "photo_gps"}
        return days
    days = set(cached([TRACK_POINTS, LOCATED / "photos.csv"], load))
    for r in read_rows(PLACES_CSV):
        if r["lat"]:
            d, last = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"] or r["start_date"])
            while d <= last:
                days.add(d.isoformat())
                d += timedelta(days=1)
    for s in rows("stays"):
        try:
            d, last = date.fromisoformat(s["first_night"]), date.fromisoformat(s["leaving"])
        except ValueError:
            continue
        while d <= last:
            days.add(d.isoformat())
            d += timedelta(days=1)
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
        out.append({"key": f"gap:{first}", "first": first.isoformat(), "last": last.isoformat(),
                    "days": (last - first).days + 1,
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
