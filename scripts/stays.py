#!/usr/bin/env python3
"""Where each night was spent, and the stays of several nights in one place, from rides and photos.

Usage: stays.py

The night of D is the one between local days D and D+1. Its candidate places are, best first:

  ride    the start of the first ride on the morning of D+1 (you leave from where you slept),
          and the end of the last ride on D (you arrive where you'll sleep)
  photo   the first geotagged photo of the morning of D+1, and the last of the evening of D
  day     failing those, the first fix of D+1 before day_morning or the last of D after
          day_evening, whatever it is

The evening of D runs on to night_ends on D+1, when the morning starts: a ride home that ends
at 00:24 is the evening's. (Hours are in settings.yaml, under stays.)

Of these, the night takes the one that the most other nights within support_days also have a
candidate near: the room you keep coming back to beats an evening photo at a restaurant.
Without any such support it takes the best.

A stay starts at a night and takes in the following nights within radius_km of it. It carries on
over bridged nights with no candidates, as long as nothing on those days was more than bridge_km
away (rest days, with nothing recorded), and over up to max_away nights elsewhere (a night out, a
trip) if a night back in the same place follows. Other places the stay's nights were within
note_km of are noted, by how many nights: a guesthouse 600 m from the one counted, which may be
where you really slept.

Writes processing/stays/found.json, for the review app's Stays view, which compares these with
manual/stays.csv (the stays you've checked, which make route uses):
  stays   each stay of min_nights or more: first_night, leaving (the morning after the last
          night), place (lat, lon, plus code, town), the evidence its nights had (counts of ride,
          photo, day, bridged), the nights away from it and the other places close by
  nights  every night's candidates: lat, lon, evidence, and whether it was chosen
"""
import sys
from datetime import date, datetime, time, timedelta

from openlocationcode import openlocationcode as olc

from common.geo import distance_km
from common.photos import gps_photos
from common.tables import read_rows, write_json
from common.times import local_offsets, parse
from common.towns import Towns
from repo import FOUND_STAYS, INDEX
from settings import settings

EVIDENCE = ("ride", "photo", "day", "bridged")
S = settings.stays


def plus_code(lat, lon):
    """The full 10-digit Open Location Code."""
    return olc.encode(lat, lon)


def rides():
    """(start, end) of each recorded ride, each a (utc, lat, lon), from the rides index."""
    import json
    found = []
    for r in read_rows(INDEX / "rides.csv"):
        for start, slat, slon, end, elat, elon, *_ in json.loads(r["rides"]):
            found.append(((parse(start), slat, slon), (parse(end), elat, elon)))
    return found


class Fixes:
    """Timed positions by local day, so each night can ask for its evening and morning."""

    def __init__(self, offsets):
        self.offsets = offsets
        self.by_day = {}

    def add(self, kind, utc, lat, lon):
        local = (utc + (self.offsets.points[self.offsets.nearest(utc.replace(tzinfo=None))][1]
                        if self.offsets.points else timedelta())).replace(tzinfo=None)
        self.by_day.setdefault(local.date(), []).append((local, kind, lat, lon))

    def on(self, day, kinds=("ride_start", "ride_end", "photo"), after=0, before=24):
        """Fixes of the given kinds on local day, between the local hours, time-sorted."""
        lo = datetime.combine(day, time(after))
        hi = datetime.combine(day, time()) + timedelta(hours=before)
        return sorted(f for f in self.by_day.get(day, []) if f[1] in kinds and lo <= f[0] < hi)


def candidates(fixes, day):
    """(lat, lon, evidence) places the night of day may have been, best first."""
    after = day + timedelta(days=1)

    def evening(kinds, start=0):
        return fixes.on(day, kinds, after=start) + fixes.on(after, kinds, before=S.night_ends)

    def morning(kinds, end):
        return fixes.on(after, kinds, after=S.night_ends, before=end)

    choices = [
        ("ride", morning({"ride_start"}, S.ride_morning)[:1]),
        ("ride", evening({"ride_end"})[-1:]),
        ("photo", morning({"photo"}, S.photo_morning)[:1]),
        ("photo", evening({"photo"}, S.photo_evening)[-1:]),
    ]
    found = [(lat, lon, evidence) for evidence, fs in choices for _, _, lat, lon in fs]
    if not found:
        kinds = ("ride_start", "ride_end", "photo")
        fs = morning(kinds, S.day_morning)[:1] + evening(kinds, S.day_evening)[-1:]
        found = [(lat, lon, "day") for _, _, lat, lon in fs]
    return found


def near(a, b, km):
    return distance_km(a[0], a[1], b[0], b[1]) <= km


def choose(options):
    """The place for each night: its candidate with the most support from nearby nights."""
    nights = {}
    for d, mine in options.items():
        def support(c):
            return sum(1 for o in range(-S.support_days, S.support_days + 1)
                       if o and any(near(c, x, S.radius_km) for x in options.get(d + timedelta(days=o), [])))
        # max keeps the first of equals, so the best evidence wins a tie
        nights[d] = max(mine, key=support) if mine else None
    return nights


def stays(nights, fixes):
    """Stays: dicts of place, nights [(day, place or None)] and away [(day, place)]."""
    days = sorted(nights)
    found, i = [], 0
    while i < len(days):
        anchor = nights[days[i]]
        if anchor is None:
            i += 1
            continue
        stay = {"place": anchor, "nights": [(days[i], anchor)], "away": []}
        pending, j = [], i + 1
        while j < len(days):
            day, place = days[j], nights[days[j]]
            if place and near(place, anchor, S.radius_km):
                stay["nights"] += pending + [(day, place)]
                stay["away"] += [(d, p) for d, p in pending if p]
                pending = []
            else:
                pending.append((day, place))
                away = [p for _, p in pending if p]
                quiet = all(near(f[2:], anchor, S.bridge_km)
                            for d, p in pending if p is None for f in fixes.by_day.get(d, []))
                if len(away) > S.max_away or not quiet:
                    break
            j += 1
        found.append(stay)
        # What didn't fit this stay starts the search for the next
        i = days.index(pending[0][0]) if pending else j
    return found


def describe(stay, towns):
    """A found stay as the review app shows it: facts, not a sentence."""
    days = [d for d, _ in stay["nights"]]
    lat, lon, _ = stay["place"]
    away_days = {d for d, _ in stay["away"]}
    counts = {}
    for d, place in stay["nights"]:
        if d not in away_days:
            evidence = place[2] if place else "bridged"
            counts[evidence] = counts.get(evidence, 0) + 1
    # Other places close by, grouped and counted: maybe another room, maybe the real one
    others, away = [], []
    for d, place in stay["away"]:
        if near(place, stay["place"], S.note_km):
            for group in others:
                if near(place, group["at"], S.radius_km):
                    group["nights"].append(d.isoformat())
                    break
            else:
                others.append({"at": place, "nights": [d.isoformat()]})
        else:
            away.append({"night": d.isoformat(), "town": towns.describe(place[0], place[1]),
                         "lat": place[0], "lon": place[1], "plus_code": plus_code(place[0], place[1])})
    first, leaving = days[0], days[-1] + timedelta(days=1)
    code = plus_code(lat, lon)
    return {"key": f"{first}:{code}", "first_night": first.isoformat(), "leaving": leaving.isoformat(),
            "nights": len(days), "night_dates": [d.isoformat() for d in days],
            "lat": lat, "lon": lon, "plus_code": code, "town": towns.describe(lat, lon),
            "evidence": {k: counts[k] for k in EVIDENCE if k in counts}, "away": away,
            "others": [{"plus_code": plus_code(*g["at"][:2]), "lat": g["at"][0], "lon": g["at"][1],
                        "nights": g["nights"]} for g in others]}


def analyse(towns):
    """(options, nights, found stays) over the trip."""
    fixes = Fixes(local_offsets())
    for a, b in rides():
        fixes.add("ride_start", *a)
        fixes.add("ride_end", *b)
    for utc, lat, lon in gps_photos(towns):
        fixes.add("photo", utc, lat, lon)
    options, day = {}, settings.trip.start
    while day < settings.trip.end:
        options[day] = candidates(fixes, day)
        day += timedelta(days=1)
    nights = choose(options)
    return options, nights, stays(nights, fixes)


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    towns = Towns()
    options, nights, found = analyse(towns)
    listed = [describe(s, towns) for s in found if len(s["nights"]) >= S.min_nights]
    night_data = {}
    for d, cands in options.items():
        chosen = nights.get(d)
        if cands:
            night_data[d.isoformat()] = [{"lat": round(lat, 6), "lon": round(lon, 6), "evidence": ev,
                                          "chosen": chosen is not None and (lat, lon) == chosen[:2]}
                                         for lat, lon, ev in cands]
    write_json(FOUND_STAYS, {"radius_km": S.radius_km, "stays": listed, "nights": night_data}, indent=None)
    print(f"{len(listed)} stays of {S.min_nights}+ nights found, from {len(night_data)} nights with a place")


if __name__ == "__main__":
    main()
