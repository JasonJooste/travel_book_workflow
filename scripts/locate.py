#!/usr/bin/env python3
"""When and where each photo, recording, written entry and blog post was made.

Usage: locate.py

Reads the per-file facts of make index (EXIF times and GPS, recording times, dates in names)
and places each file in time and space. Writes, in processing/located:

  photos.csv   photos and videos taken on the trip's local days
  audio.csv    every diary recording, with its best transcript (provider order: deepgram, openai,
               elevenlabs, whisper, then the old local ones in processing/asr/local)
  written.csv  every written diary file; fragments and themes have no date
  blog.csv     every blog post, which have no date, and every Komoot description on the trip's days,
               at the start of its ride

Each row has file, utc, local_date, lat, lon, town, country and position_source. Positions are,
best first: the file's own GPS (photo_gps); the GPS point (track or photo) nearest in time, if
within locate.gps_hours; a known place (make places) covering the day, or a timed one within
locate.pass_hours; the nearest point the route (make route) put in a gap, within
locate.predicted_hours; otherwise the GPS point nearest in time, within lookup.max_hours. Local
dates use the UTC offset nearest in time: of a ride (make track's offsets.csv, from the phone's
GPX times), or of a photo, from the gap between its camera clock (local) and its GPS clock (UTC);
or, where those are days away, the time zone of the nearest GeoNames town, as in Brisbane and
Taipei, before the first photo with GPS. Known places' times are local too, unless they end in Z.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common import photos as photo_index
from common.tables import read_rows, write_rows
from common.times import parse, place_time, stamp
from common.towns import Towns
from common.track import Track
from repo import ASR, INDEX, KOMOOT_TOURS, LOCATED, PLACES_CSV, ROUTE, TRACK_POINTS, rel
from settings import settings

PLACE = ["file", "utc", "local_date", "lat", "lon", "town", "country", "position_source"]
PROVIDERS = ("deepgram", "openai", "elevenlabs", "whisper")
L = settings.locate


class KnownPlaces:
    """Known places: rows without a time cover their days, timed ones locate.pass_hours either side."""

    def __init__(self, offsets, towns):
        self.days, self.times = {}, []
        for r in read_rows(PLACES_CSV):
            if not r["lat"]:
                continue
            place = (float(r["lat"]), float(r["lon"]))
            if r["time"]:
                noon = datetime.fromisoformat(r["start_date"] + "T12:00")
                when = place_time(r["start_date"], r["time"], offsets, towns.zone(*place) if offsets.far(noon) else None)
                self.times.append((when, place))
                continue
            day, end = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"] or r["start_date"])
            while day <= end:
                self.days.setdefault(day, []).append(place)
                day += timedelta(days=1)

    def at(self, utc, local_date):
        """(lat, lon) or None. On a day two rows share, mornings take the first (where the night was)."""
        for when, place in self.times:
            if utc and abs(utc - when) <= timedelta(hours=L.pass_hours):
                return place
        places = self.days.get(date.fromisoformat(str(local_date))) if local_date else None
        if places:
            return places[0] if utc and utc.hour < 12 else places[-1]
        return None


class Places:
    """Where a file was, for a time and maybe a position of its own."""

    def __init__(self, track, towns, known, predicted):
        self.track, self.towns, self.known, self.predicted = track, towns, known, predicted

    def find(self, utc, local_date, lat=None, lon=None):
        """(lat, lon, position_source), the lat and lon None where nothing says."""
        if lat is not None:
            return lat, lon, "photo_gps"
        pos = self.track.position(utc) if utc else None
        guess = self.predicted.position(utc) if utc and self.predicted.points else None
        if pos and pos[2] <= L.gps_hours:
            return pos[0], pos[1], pos[3]
        if known := self.known.at(utc, local_date):
            return known[0], known[1], "known_place"
        if guess and guess[2] <= L.predicted_hours:
            return guess[0], guess[1], guess[3]
        if pos:
            return pos[0], pos[1], pos[3]
        return None, None, ""

    def zone(self, where):
        """The time zone of a place found, or None."""
        return self.towns.zone(where[0], where[1]) if where[0] is not None else None

    def row(self, file, utc, local_date, where):
        lat, lon, source = where
        town = self.towns.nearest(lat, lon) if lat is not None else None
        return {"file": file, "utc": stamp(utc) if utc else "", "local_date": local_date or "",
                "lat": f"{lat:.5f}" if lat is not None else "", "lon": f"{lon:.5f}" if lon is not None else "",
                "town": town[0] if town else "", "country": town[1] if town else "", "position_source": source}


def predicted_route():
    """Points the route put in gaps (make route), or none if it hasn't run."""
    track = Track()
    track.add((parse(r["utc"]), float(r["lat"]), float(r["lon"]), "predicted_route")
              for r in read_rows(ROUTE / "route.csv") if r["source"] in ("routed", "straight"))
    return track


def photo_rows(rows, offsets, places):
    found = photo_index.timed(rows, offsets, lambda utc, day, lat, lon: places.find(utc, day, lat, lon), places.zone)
    return [{**places.row(p["file"], p["utc"], p["local_date"], p["place"]), "kind": p["kind"],
             "time_source": p["time_source"]} for p in found]


def transcript(stem):
    """(path, source, language, words) of the best transcript: a provider's, else the old local one."""
    for provider in PROVIDERS:
        path = ASR / provider / f"{stem}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            return path, provider, record.get("language") or "", len(record["text"].split())
    path = ASR / "local" / f"{stem}.txt"
    if path.exists():
        return path, "local", "", len(path.read_text(encoding="utf-8").split())
    return None, "", "", ""


def audio_rows(offsets, places):
    out = []
    for r in read_rows(INDEX / "audio.csv"):
        utc = local = None
        if r["date_source"] == "wav_header":
            utc = datetime.strptime(r["recorded"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            local = offsets.local(utc)
        elif r["date_source"] == "filename":  # file names carry local time
            local = datetime.fromisoformat(r["recorded"])
            utc = offsets.utc(local)
        where = places.find(utc, local.date() if local else None)
        row = places.row(r["file"], utc, local.date() if local else None, where)
        # Once the place is known, its time zone may say the time was another
        zone = places.zone(where) if (utc or local) and offsets.far(utc or local) else None
        if zone and r["date_source"] == "wav_header":
            better = offsets.local(utc, zone)
            if better.date() != local.date():
                row = places.row(r["file"], utc, better.date(), places.find(utc, better.date()))
        elif zone and r["date_source"] == "filename":
            better = offsets.utc(local, zone)
            if better != utc:
                row = places.row(r["file"], better, local.date(), places.find(better, local.date()))
        path, source, language, words = transcript(Path(r["file"]).stem)
        out.append({**row, "date_source": r["date_source"], "duration_min": r["duration_min"],
                    "transcript": rel(path) if path else "", "transcript_source": source,
                    "language": language, "words": words})
    return sorted(out, key=lambda r: r["utc"])


def written_rows(places):
    out = []
    for r in read_rows(INDEX / "written.csv"):
        day = date.fromisoformat(r["date"]) if r["date"] else None
        # No time of day, so the position is the track's at midday
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc) if day else None
        out.append({**places.row(r["file"], None, day, places.find(noon, day)), "words": r["words"]})
    return sorted(out, key=lambda r: (str(r["local_date"]) or "9999", r["file"]))


def blog_rows(places):
    starts = {r["id"]: parse(r["start_utc"]) for r in read_rows(KOMOOT_TOURS)}
    out = []
    for r in read_rows(INDEX / "blog.csv"):
        if r["kind"] == "komoot":
            day = date.fromisoformat(r["date"])
            if not settings.trip.start <= day <= settings.trip.end:
                continue
            utc = starts.get(r["tour"]) or datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
            row = places.row(r["file"], utc, day, places.find(utc, day))
        else:
            row = places.row(r["file"], None, None, places.find(None, None))
        out.append({**row, "kind": r["kind"], "words": r["words"]})
    return sorted(out, key=lambda r: (str(r["local_date"]) or "9999", r["file"]))


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    rows = photo_index.read()
    offsets = photo_index.index_offsets(rows)
    track = Track(TRACK_POINTS)
    fixes = [photo_index.parsed(r) for r in rows]
    track.add((utc, lat, lon, "nearby_photo") for _, utc, _, lat, lon in fixes if utc and lat is not None)
    towns = Towns()
    places = Places(track, towns, KnownPlaces(offsets, towns), predicted_route())
    for name, found, extra in (
            ("photos", photo_rows(rows, offsets, places), ["kind", "time_source"]),
            ("audio", audio_rows(offsets, places),
             ["date_source", "duration_min", "transcript", "transcript_source", "language", "words"]),
            ("written", written_rows(places), ["words"]),
            ("blog", blog_rows(places), ["kind", "words"])):
        n = write_rows(LOCATED / f"{name}.csv", PLACE + extra, found)
        print(f"{rel(LOCATED / name)}.csv: {n} rows")


if __name__ == "__main__":
    main()
