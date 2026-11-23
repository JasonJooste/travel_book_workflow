#!/usr/bin/env python3
"""Coordinates for the known places, from GeoNames; and the questions where a town is unclear.

Usage: places.py

manual/known_places.csv (docs/known_places.md) says where the trip was when no GPS does. Each
row's town is looked up in its country's full GeoNames dump, downloaded once into
processing/geonames (it has the villages, capes and parks cities500 leaves out). A row with its
own lat,lon is taken as it is.

Populated places are preferred over other features (hills, farms, airports), and matches within
places_spread_km of each other are one place (a town, its district, its airport). A town that
matches one place gets it. Where it matches several further apart, or none, the answer in
manual/place_picks.csv is used: you give it in the review app's Places view, which shows the
options on a map beside the GPS points around the row's dates.

Writes, in processing/places:
  places.csv      the rows, plus lat, lon, the GeoNames name, feature code and region, and how many
                  places matched; rows still unanswered have no lat,lon
  questions.json  each unanswered row: its options and the GPS points around it, for the Places view
"""
import bisect
import io
import re
import sys
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone

from common.geo import distance_km
from common.tables import read_rows, write_bytes, write_json, write_rows
from common.times import exif_time
from common.towns import Towns
from common.track import Track
from repo import GEONAMES, INDEX, KNOWN_PLACES_CSV, PLACE_PICKS_CSV, PLACE_QUESTIONS, PLACES_CSV, TRACK_POINTS
from settings import settings

DUMP_URL = "https://download.geonames.org/export/dump/"
PICK_FIELDS = ["town", "country", "geonameid", "name", "lat", "lon"]
KNOWN_FIELDS = ["id", "start_date", "end_date", "time", "town", "country", "note", "lat", "lon"]


def normalise(name):
    """Lower case, no accents or punctuation: 'Guardiola de Berguedà' -> 'guardiola de bergueda'."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in plain.lower()).split())


def download(name):
    """processing/geonames/name, downloaded if missing; zips are unpacked to their .txt."""
    path = GEONAMES / name.replace(".zip", ".txt")
    if not path.exists():
        print(f"downloading {DUMP_URL}{name}", file=sys.stderr)
        with urllib.request.urlopen(DUMP_URL + name, timeout=300) as response:
            data = response.read()
        write_bytes(path, zipfile.ZipFile(io.BytesIO(data)).read(path.name) if name.endswith(".zip") else data)
    return path


def country_codes():
    """Normalised country name or ISO code -> ISO code, from countryInfo.txt."""
    codes = {}
    for line in download("countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            cols = line.split("\t")
            codes[normalise(cols[0])] = codes[normalise(cols[4])] = cols[0]
    return codes


def regions():
    """'ZA.11' -> 'Western Cape', from admin1CodesASCII.txt."""
    lines = download("admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("\t")[:2] for line in lines)


def country_places(code, region_names):
    """Normalised name -> {place tuple} for one country."""
    index = {}
    with download(f"{code}.zip").open(encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            place = (cols[0], cols[1], float(cols[4]), float(cols[5]), f"{cols[6]}.{cols[7]}",
                     region_names.get(f"{code}.{cols[10]}", ""), int(cols[14] or 0))
            for name in {cols[1], cols[2], *cols[3].split(",")}:
                if name:
                    index.setdefault(normalise(name), set()).add(place)
    return index


def candidates(index, town):
    """Distinct places a town could be, as dicts; a place listed several times counts once.
    A town can name its region in brackets where the name is shared: Strandfontein (Western Cape)."""
    town, region = re.fullmatch(r"(.*?)\s*(?:\((.*)\))?", town.strip()).groups()
    found = [dict(zip(("id", "name", "lat", "lon", "feature", "region", "population"), p))
             for p in index.get(normalise(town), set())
             if not region or normalise(region) in normalise(p[5])]
    found = [p for p in found if p["feature"].startswith("P.")] or found
    distinct = []
    # Populated places first, so the town stands for its district and airport
    for p in sorted(found, key=lambda p: (not p["feature"].startswith("P.P"), p["id"])):
        if all(distance_km(p["lat"], p["lon"], q["lat"], q["lon"]) > settings.places_spread_km for q in distinct):
            distinct.append(p)
    return distinct


def gps():
    """The track plus photo GPS, as a Track."""
    track = Track(TRACK_POINTS)
    track.add((exif_time(r["gps_time"]).replace(tzinfo=timezone.utc), float(r["lat"]), float(r["lon"]), "photo")
              for r in read_rows(INDEX / "photos.csv") if r["gps_time"] and r["lat"] and r["lon"])
    return track


def neighbours(row, track, towns, previous, following):
    """[{label, when, source, name, lat, lon}] for the GPS points just before, during (the middle one)
    and after a row's dates; the previous or next settled row's place stands in where there's no GPS."""
    def point(label, i):
        utc, lat, lon, source = track.points[i]
        near = towns.nearest(lat, lon)
        return {"label": label, "when": utc.strftime("%Y-%m-%dT%H:%MZ"), "source": source,
                "name": near[0] if near else "", "lat": lat, "lon": lon}

    found = []
    start = datetime.fromisoformat(row["start_date"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(row["end_date"] or row["start_date"]).replace(hour=23, minute=59, tzinfo=timezone.utc)
    i, j = bisect.bisect_left(track.times, start), bisect.bisect_right(track.times, end)
    if i > 0:
        found.append(point("before", i - 1))
    if i < j:
        found.append(point("during", (i + j) // 2))
    if j < len(track.points):
        found.append(point("after", j))
    labels = {n["label"] for n in found}
    for label, side, (other, place) in (("before", "previous row", previous), ("after", "next row", following)):
        if label not in labels and place:
            n = {"label": side, "when": other["start_date"], "source": "known place", "name": other["town"],
                 "lat": place["lat"], "lon": place["lon"]}
            found.insert(0, n) if label == "before" else found.append(n)
    return found


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    rows = [r for r in read_rows(KNOWN_PLACES_CSV, missing_ok=False)
            if r["town"].strip() or (r.get("lat") and r.get("lon"))]
    picks = {(normalise(p["town"]), p["country"]): p for p in read_rows(PLACE_PICKS_CSV)}
    codes, region_names = country_codes(), regions()
    by_country, options, chosen, why = {}, [], [], []
    for r in rows:
        if r.get("lat") and r.get("lon"):
            options.append([])
            chosen.append({"id": "", "name": r["town"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                           "feature": "given", "region": ""})
            why.append("")
            continue
        code = codes.get(normalise(r["country"]))
        found = []
        if code is not None:
            if code not in by_country:
                by_country[code] = country_places(code, region_names)
            found = candidates(by_country[code], r["town"])
        pick = picks.get((normalise(r["town"]), code))
        if pick and not pick["geonameid"]:
            pick = {"id": "", "name": pick["name"], "lat": float(pick["lat"]), "lon": float(pick["lon"]),
                    "feature": "custom", "region": ""}
        elif pick:
            pick = next((p for p in found if p["id"] == pick["geonameid"]), None)
        options.append(found)
        chosen.append(pick or (found[0] if len(found) == 1 else None))
        why.append("unknown_country" if code is None else "no_match" if not found else "ambiguous")

    questions = []
    track = towns = None
    for i, (r, found) in enumerate(zip(rows, options)):
        if chosen[i]:
            continue
        if track is None:
            track, towns = gps(), Towns()
        previous = next(((rows[j], chosen[j]) for j in range(i - 1, -1, -1) if chosen[j]), (None, None))
        following = next(((rows[j], chosen[j]) for j in range(i + 1, len(rows)) if chosen[j]), (None, None))
        near = neighbours(r, track, towns, previous, following)
        # Nearest the neighbours first
        found = sorted(found, key=lambda p: sum(distance_km(p["lat"], p["lon"], n["lat"], n["lon"]) for n in near))
        for p in found:
            p["km_from"] = {n["label"]: round(distance_km(p["lat"], p["lon"], n["lat"], n["lon"]), 1) for n in near}
        questions.append({"row": {k: r.get(k, "") for k in KNOWN_FIELDS}, "country_code": codes.get(normalise(r["country"])),
                          "reason": why[i], "options": found, "neighbours": near})

    for r, found, p in zip(rows, options, chosen):
        p = p or {}
        r.update(lat=p.get("lat", ""), lon=p.get("lon", ""), geoname=p.get("name", ""),
                 feature=p.get("feature", ""), region=p.get("region", ""), matches=len(found))
    write_rows(PLACES_CSV, KNOWN_FIELDS + ["geoname", "feature", "region", "matches"], rows)
    write_json(PLACE_QUESTIONS, questions)
    print(f"{PLACES_CSV.relative_to(PLACES_CSV.parents[2])}: {len(rows)} places, {len(questions)} to answer "
          "in the review app's Places view" if questions else f"{len(rows)} places, all settled")


if __name__ == "__main__":
    main()
