"""The Places view's data: towns to settle, days with no position, and your known places.

  GET /api/places   questions  each known place make places couldn't settle: its row, why (several
                               places match, none does, or the country isn't known), the options with
                               their distance from the GPS points around its dates, and those points
                    gaps       each run of days with nothing to say where you were: no ride, no photo
                               with GPS, no known place and no stay. With the photos and diary entries
                               of those days, which may say
                    known      every row of manual/known_places.csv, with its looked-up position
"""
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


def gaps():
    covered = covered_days()
    entries = {}
    for name in ("audio", "written", "blog"):
        for r in read_rows(LOCATED / f"{name}.csv"):
            if r["local_date"]:
                entries.setdefault(r["local_date"], []).append({"kind": r.get("kind") or name, "file": r["file"],
                                                                "stem": Path(r["file"]).stem, "words": r["words"],
                                                                "utc": r["utc"]})
    photos = {}
    for r in read_rows(LOCATED / "photos.csv"):
        photos.setdefault(r["local_date"], []).append({"file": r["file"], "name": Path(r["file"]).name,
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
        days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
        out.append({"key": f"gap:{first}", "first": first.isoformat(), "last": last.isoformat(), "days": len(days),
                    "entries": [e for d in days for e in entries.get(d, [])],
                    "photos": [p for d in days for p in photos.get(d, [])][:60]})
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
