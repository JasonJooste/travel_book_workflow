#!/usr/bin/env python3
"""What looks wrong in the built route, and what could be labelled: one list of findings.

Usage: checks.py

Reads what make route wrote in processing/route, the track, the OSM waterways (make osm), the
Komoot tours, manual/travel_modes.csv and processing/places/places.csv, and writes
processing/route/findings.json: one finding per thing to look at, in time order, for the Route
view of the review app. Each has

  id          stable while the finding is the same check over the same span and place
  check       which check found it (below)
  title       a few words saying what it is
  start_utc, end_utc, lat, lon
  facts       the numbers and names behind it, as fields (km, hours, kmh, limit_kmh, from, to,
              mode, ...), never inside a sentence: the review app lays them out
  rows        the ids of the manual rows it's about: {"travel_modes": [...], "known_places": [...]}
  fix         what the review app offers to do about it, if anything: label a span with a mode,
              delete rows, keep one of two, move a point onto the route, remove known places
  dismissed   the id of the manual/dismissed.csv row that dismissed it, or absent
  detail      the one line make check would print about it

A dismissal (Looks fine, in the review app) covers a finding of the same check at the same place
(within checks.dismiss_deg) whose span overlaps its own, so one comes back if its place moves or
it turns up at another time, but not when a reroute nearby shifts its span by a few minutes.

The checks:
  unlabelled     a stretch still predicted, or a point with no known class
  gpx            route.gpx isn't whole: a track that doesn't start where the last ended, times going
                 backwards, a jump no gap leg fills, a type that isn't a class, a different number of
                 points from route.csv
  unmatched_row  a travel mode row that's part of no gap leg and takes in no recorded step
  overlap        two rows of different modes over checks.overlap_min or more of the same time, or the
                 same row twice
  long_row       a row longer than checks.long_row_days labelling checks.long_row_legs or more gap legs
  mode_switch    a short run of one mode between two runs of another, switched into and out of quickly,
                 or a very short run of a vehicle
  fast           a leg, or steps inside a ride, faster than its mode allows (modes' max_kmh)
  long_day       more than checks.day_km cycled in a (UTC) day
  straight       a road leg drawn straight, as no route was found; a bike leg routed as a car; a short flight
  spike          the route goes out to a photo, known place or stay and straight back
  detour         a leg routed over checks.detour times the straight line
  unused_point   a known place with its own lat,lon that the route doesn't pass through
  crossing       a ride crosses a river with no bridge in OSM: a boat, or a ford
  suggestion     a mode the speeds suggest: a Komoot hike, a lift during one, a bus or lift elsewhere
"""
import bisect
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common.geo import Flat, distance_km
from common.tables import read_rows as rows, write_json
from common.times import parse as when, stamp
from repo import DISMISSED_CSV, FINDINGS, KOMOOT_TOURS, MODES_CSV, PLACES_CSV, ROUTE, TRACK_POINTS, WATERWAYS
from route import CLASSES, GAP_KM, covers, inside_ride, read_modes
from settings import settings

C = settings.checks
LEG_KMH = {"predicted": settings.modes["cycled"].max_kmh,
           **{m: v.max_kmh for m, v in settings.modes.items() if v.max_kmh}}
VEHICLES = tuple(m for m, v in settings.modes.items() if v.vehicle)
ROAD_CLASSES = ("predicted", *(m for m, v in settings.modes.items() if v.router != "none"))
FIXED = ("photo", "known_place", "stay")
TITLES = {
    "unlabelled": "Still unlabelled", "gpx": "route.gpx isn't whole", "unmatched_row": "Row labels nothing",
    "overlap": "Rows overlap", "long_row": "Row runs for days", "mode_switch": "Quick switch of mode",
    "fast": "Too fast", "long_day": "Long day", "straight": "Drawn straight", "spike": "Out and straight back",
    "detour": "Long detour", "unused_point": "Known place not on the route", "crossing": "River crossing",
    "suggestion": "Suggested mode",
}


def finding(check, start, end, lat, lon, detail, title=None, rows=None, fix=None, **facts):
    """A finding: detail is the one line make check prints; facts the values behind it."""
    key = f"{check}|{stamp(start)}|{stamp(end)}|{lat:.4f}|{lon:.4f}"
    return {"id": hashlib.sha1(key.encode()).hexdigest()[:10], "check": check, "title": title or TITLES[check],
            "start_utc": stamp(start), "end_utc": stamp(end), "lat": round(lat, 6), "lon": round(lon, 6),
            "facts": {k: v for k, v in facts.items() if v not in (None, "")},
            "rows": {k: v for k, v in (rows or {}).items() if v}, **({"fix": fix} if fix else {}), "detail": detail}


def dismisses(ok, f):
    """Whether a row of manual/dismissed.csv dismisses finding f: the same check, at the same place to
    within checks.dismiss_deg, over spans that overlap."""
    try:
        same_place = (abs(float(ok["lat"]) - f["lat"]) <= C.dismiss_deg
                      and abs(float(ok["lon"]) - f["lon"]) <= C.dismiss_deg)
    except (KeyError, ValueError):
        return False
    return (ok["check"].strip() == f["check"] and same_place
            and ok["start_utc"].strip() <= f["end_utc"] and f["start_utc"] <= ok["end_utc"].strip())


def hours(a, b):
    """Hours from a to b, at least a minute: times are to the minute."""
    return max((b - a).total_seconds(), 60) / 3600


class Route:
    """route.csv's points, and which steps between them are gap legs."""

    def __init__(self):
        self.points = [(when(r["utc"]), float(r["lat"]), float(r["lon"]), r["class"], r["source"], r["ref"])
                       for r in rows(ROUTE / "route.csv")]
        self.times = [p[0] for p in self.points]
        self.legs = rows(ROUTE / "legs.csv")
        for g in self.legs:
            g["a"], g["b"] = when(g["start_utc"]), when(g["end_utc"])
            g["km"], g["straight"] = float(g["routed_km"]), float(g["straight_km"])
        spans = {(g["a"], g["b"]) for g in self.legs}
        # The fixed and recorded points, and the steps between them that aren't gap legs
        self.anchors = [p for p in self.points if p[4] not in ("routed", "straight")]
        self.steps = [(a, b) for a, b in zip(self.anchors, self.anchors[1:]) if (a[0], b[0]) not in spans]
        self.step_starts = [a[0] for a, _ in self.steps]

    def at(self, t):
        """The point at or just after t."""
        return self.points[min(bisect.bisect_left(self.times, t), len(self.points) - 1)]


def read_gpx():
    """[(type, [(utc or None, lat, lon), ...]), ...] per track of route.gpx."""
    ns = "{http://www.topografix.com/GPX/1/1}"
    tracks = []
    for trk in ET.parse(ROUTE / "route.gpx").getroot().iter(ns + "trk"):
        points = []
        for pt in trk.iter(ns + "trkpt"):
            text = pt.findtext(ns + "time")
            t = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if text else None
            points.append((t, float(pt.get("lat")), float(pt.get("lon"))))
        tracks.append((trk.findtext(ns + "type") or "", points))
    return tracks


def label_fix(start, end, mode, note=""):
    """A fix that adds a travel mode row: UTC start and end as travel_modes.csv has them."""
    return {"action": "label", "start": stamp(start)[:-1], "end": stamp(end)[:-1], "mode": mode, "note": note}


def check_unlabelled(route):
    for r in rows(ROUTE / "unlabelled.csv"):
        start, end = when(r["start_utc"]), when(r["end_utc"])
        p = route.at(start)
        yield finding("unlabelled", start, end, p[1], p[2], f"{r['km']} km still predicted, {r['from']} to {r['to']}",
                      fix=label_fix(start, end, "cycled"), km=float(r["km"]), steps=int(r["steps"]),
                      **{"from": r["from"], "to": r["to"]})
    run = []
    for p in route.points + [None]:
        if p and p[3] not in CLASSES:
            run.append(p)
        elif run:
            yield finding("unlabelled", run[0][0], run[-1][0], run[0][1], run[0][2],
                          f"{len(run)} points with the class {run[0][3]!r}, which isn't one of {' '.join(CLASSES)}",
                          title="Unknown class", points=len(run), **{"class": run[0][3]})
            run = []


def check_gpx(route, tracks):
    spans = sorted((g["a"], g["b"]) for g in route.legs)
    starts = [a for a, _ in spans]

    def in_leg(t0, t1):
        i = bisect.bisect_right(starts, t0.replace(second=0))
        return any(a <= t0.replace(second=0) and t1 <= b + timedelta(minutes=1) for a, b in spans[max(i - 2, 0):i])

    def gpx(start, end, lat, lon, problem):
        return finding("gpx", start, end, lat, lon, problem, problem=problem)

    unlabelled = [(when(r["start_utc"]), when(r["end_utc"])) for r in rows(ROUTE / "unlabelled.csv")]
    last = None
    for kind, points in tracks:
        if not points:
            continue
        first = points[0]
        if kind == "predicted" and first[0] and points[-1][0] and not any(
                a <= first[0].replace(second=0) and points[-1][0].replace(second=0) <= b for a, b in unlabelled):
            yield gpx(first[0], points[-1][0], first[1], first[2],
                      "a predicted track that unlabelled.csv doesn't list: make route again")
        if kind not in CLASSES:
            yield gpx(first[0] or route.times[0], points[-1][0] or route.times[0], first[1], first[2],
                      f"a track of type {kind!r}, which isn't one of {' '.join(CLASSES)}")
        if last and (distance_km(*last[1:], *first[1:]) > 0.01 or last[0] != first[0]):
            yield gpx(last[0] or first[0], first[0] or last[0], first[1], first[2],
                      f"this track starts {distance_km(*last[1:], *first[1:]):.1f} km from where the last one "
                      f"ended, at {last[0]:%Y-%m-%d %H:%M}Z")
        for p, q in zip(points, points[1:]):
            if p[0] is None or q[0] is None:
                yield gpx(p[0] or q[0] or route.times[0], q[0] or p[0] or route.times[0], q[1], q[2],
                          "a point with no time")
            elif q[0] < p[0]:
                yield gpx(q[0], p[0], q[1], q[2], "times go backwards here")
            elif distance_km(*p[1:], *q[1:]) > GAP_KM and not in_leg(p[0], q[0]):
                yield gpx(p[0], q[0], p[1], p[2], f"a jump of {distance_km(*p[1:], *q[1:]):.1f} km inside a {kind} "
                          "track that no gap leg routes: a hole in the route")
        last = points[-1]
    count = sum(len(points) for _, points in tracks) - max(len(tracks) - 1, 0)  # tracks share their ends
    if count != len(route.points):
        p = route.points[0]
        yield gpx(p[0], route.times[-1], p[1], p[2], f"route.gpx has {count} points and route.csv "
                  f"{len(route.points)}: make route again")
    ends = [points for _, points in tracks if points]
    if ends:
        for name, g, r in (("starts", ends[0][0], route.points[0]), ("ends", ends[-1][-1], route.points[-1])):
            if g[0] is None or abs(g[0] - r[0]) > timedelta(minutes=1) or distance_km(*g[1:], r[1], r[2]) > 0.01:
                yield gpx(r[0], r[0], r[1], r[2], f"route.gpx {name} somewhere other than route.csv does")


def name(row):
    return f"{row[0]:%Y-%m-%d %H:%M} to {row[1]:%Y-%m-%d %H:%M} {row[2]}" + (f" ({row[3]})" if row[3] else "")


def row_finding(check, row, route, detail, start=None, end=None, ids=(), fix=None, **facts):
    """A finding about travel mode rows, by their ids."""
    start, end = start or row[0], end or row[1]
    p = route.at(start)
    return finding(check, start, end, p[1], p[2], detail, rows={"travel_modes": list(ids)}, fix=fix, **facts)


def check_rows(route, modes):
    """Rows that match nothing (as make route decides it), overlap each other or run for days."""
    for row in modes:
        start, end = row[:2]
        over = [g for g in route.legs if g["a"] < end and start < g["b"]]
        if not any(covers(row, (g["a"],), (g["b"],)) for g in over):
            i = bisect.bisect_left(route.step_starts, start)
            if not any(b[0] <= end for a, b in route.steps[i:i + 3] if a[0] <= end):
                if over:
                    g = over[0]
                    why = (f"it overlaps the gap leg {g['from']} to {g['to']} ({g['start_utc']} to {g['end_utc']}) "
                           "but isn't inside it and covers under half of it")
                elif end < route.times[0] or start > route.times[-1]:
                    why = "it's outside the route's dates"
                else:
                    why = "no step of a ride lies wholly inside it"
                yield row_finding("unmatched_row", row, route, f"the row {name(row)} labels nothing: {why}",
                                  ids=[row[4]], fix={"action": "delete"}, mode=row[2], note=row[3], why=why)
        legs = sum(1 for g in over if covers(row, (g["a"],), (g["b"],)))
        if end - start > timedelta(days=C.long_row_days) and legs >= C.long_row_legs:
            yield row_finding("long_row", row, route,
                              f"the row {name(row)} runs {(end - start).days} days and labels {legs} gap legs at once",
                              ids=[row[4]], fix={"action": "delete"}, mode=row[2], note=row[3],
                              days=(end - start).days, legs=legs)
    ordered = sorted(modes, key=lambda r: r[:2])
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b[0] >= a[1]:
                break
            if a[:3] == b[:3]:
                yield row_finding("overlap", a, route, f"the row {name(a)} is there twice", title="Row there twice",
                                  ids=[a[4], b[4]], fix={"action": "keep_one"}, mode=a[2])
            elif a[2] != b[2] and min(a[1], b[1]) - b[0] >= timedelta(minutes=C.overlap_min):
                yield row_finding("overlap", a, route, f"rows of different modes overlap: {name(a)}, and {name(b)}",
                                  start=b[0], end=min(a[1], b[1]), ids=[a[4], b[4]], fix={"action": "keep_one"},
                                  modes=f"{a[2]}, {b[2]}", hours=round(hours(b[0], min(a[1], b[1])), 1))


def km(points):
    return sum(distance_km(*p[1:], *q[1:]) for p, q in zip(points, points[1:]))


def check_switches(tracks):
    """Short runs of a mode, from the GPX tracks, which are the runs of a class. Stops don't end a run."""
    runs = []  # [class, km, first point, last point]
    for kind, points in tracks:
        if kind == "stopped" or not points:
            continue
        if runs and runs[-1][0] == kind:
            runs[-1][1] += km(points)
            runs[-1][3] = points[-1]
        else:
            runs.append([kind, km(points), points[0], points[-1]])
    for i, (kind, length, first, last) in enumerate(runs):
        if kind in VEHICLES and length < C.vehicle_km:
            yield finding("mode_switch", first[0], last[0], first[1], first[2], f"a {kind} run of only {length:.1f} km",
                          title=f"Very short {kind} run", mode=kind, km=round(length, 1))
        elif (0 < i < len(runs) - 1 and runs[i - 1][0] == runs[i + 1][0] and length < C.switch_km
              and kind not in ("ferry", "predicted")
              and runs[i + 1][2][0] - runs[i - 1][3][0] < timedelta(hours=C.switch_hours)):
            took = (runs[i + 1][2][0] - runs[i - 1][3][0]).total_seconds() / 60
            yield finding("mode_switch", first[0], last[0], first[1], first[2],
                          f"{length:.1f} km of {kind} between two runs of {runs[i - 1][0]}, "
                          f"switched to and back within {took:.0f} minutes",
                          mode=kind, km=round(length, 1), between=runs[i - 1][0], minutes=round(took))


def leg_ends(route, g):
    """The fixed or recorded points a gap leg runs from and to: the last at its start time, the first at its end."""
    i, j = bisect.bisect_left(route.times, g["a"]), bisect.bisect_left(route.times, g["b"])
    at_a = [p for p in route.points[i:j + 1] if p[0] == g["a"] and p[4] not in ("routed", "straight")]
    at_b = [p for p in route.points[j:j + 50] if p[0] == g["b"] and p[4] not in ("routed", "straight")]
    return (at_a[-1] if at_a else None), (at_b[0] if at_b else None)


def move(p, to, places):
    """A move of route point p (a photo, known place or stay) to (lat, lon) to, which the review app
    saves as a known place of your own: its own row changed if it's one already, or a new row."""
    return {"source": p[4], "utc": stamp(p[0]), "lat": round(p[1], 6), "lon": round(p[2], 6),
            "to_lat": round(to[0], 5), "to_lon": round(to[1], 5), "km": round(distance_km(p[1], p[2], *to), 2),
            "ref": p[5], "row": own_row(places, p)}


def check_speeds(route, modes, places):
    """Legs and steps of rides too fast for their mode, with the rows that label them, and for a gap
    leg, a move of either end to the other."""
    for g in route.legs:
        limit = LEG_KMH.get(g["class"])
        speed = g["km"] / hours(g["a"], g["b"])
        if limit and g["km"] >= C.leg_km and speed > limit:
            p = route.at(g["a"])
            took = ("no time: its ends have the same minute, as via points added to a leg too short in time do"
                    if g["b"] == g["a"] else f"{hours(g['a'], g['b']):.1f} h, {speed:.0f} km/h")
            labels = [row[4] for row in modes if covers(row, (g["a"],), (g["b"],))]
            a, b = leg_ends(route, g)
            moves = [move(x, y[1:3], places) for x, y in ((b, a), (a, b)) if x and y and x[4] in FIXED]
            fix = {"action": "fast_leg", "moves": moves} if moves or labels else None
            yield finding("fast", g["a"], g["b"], p[1], p[2],
                          f"{g['from']} to {g['to']}: {g['km']:.0f} km of {g['class']} in {took}",
                          title=f"Too fast for {g['class']}", rows={"travel_modes": labels},
                          fix=fix, mode=g["class"], km=g["km"], hours=round(hours(g["a"], g["b"]), 2),
                          kmh=round(speed), limit_kmh=limit, same_minute=(g["b"] == g["a"]) or None,
                          **{"from": g["from"], "to": g["to"]})
    run = []
    for a, b in route.steps + [(None, None)]:
        fast = (a and a[4] == b[4] == "recorded" and b[3] == "cycled" and distance_km(*a[1:3], *b[1:3]) > C.step_km
                and distance_km(*a[1:3], *b[1:3]) / ((b[0] - a[0]).total_seconds() / 3600 + 1 / 60) > C.step_kmh)
        if fast and run and a[0] - run[-1][1][0] <= timedelta(minutes=C.step_join_min):
            run.append((a, b))
            continue
        if run:
            dist = sum(distance_km(*p[1:3], *q[1:3]) for p, q in run)
            start, end = run[0][0][0], run[-1][1][0]
            labels = [row[4] for row in modes if row[0] <= end and start <= row[1]]
            yield finding("fast", start, end, run[0][0][1], run[0][0][2],
                          f"{dist:.1f} km in {len(run)} step{'s' if len(run) > 1 else ''} of a ride, each over "
                          f"{C.step_kmh:.0f} km/h: a GPS jump, or a vehicle recorded as riding",
                          title="Jump inside a ride", rows={"travel_modes": labels},
                          fix=label_fix(start, end, "car"), km=round(dist, 1), steps=len(run), limit_kmh=C.step_kmh)
        run = [(a, b)] if fast else []


def check_days(tracks):
    days = {}
    for kind, points in tracks:
        if kind in ("cycled", "predicted"):
            for p, q in zip(points, points[1:]):
                if q[0]:
                    day = days.setdefault(q[0].date(), [0, q, q])
                    day[0] += distance_km(*p[1:], *q[1:])
                    day[2] = q
    for day, (dist, first, last) in sorted(days.items()):
        if dist > C.day_km:
            yield finding("long_day", first[0], last[0], first[1], first[2], f"{dist:.0f} km cycled on {day} (UTC)",
                          km=round(dist), limit_km=C.day_km, day=day.isoformat())


def check_straight(route):
    for g in route.legs:
        p = route.at(g["a"])
        ends = {"from": g["from"], "to": g["to"]}
        if g["router"] == "straight" and g["class"] in ROAD_CLASSES and g["km"] >= C.straight_km:
            yield finding("straight", g["a"], g["b"], p[1], p[2],
                          f"{g['from']} to {g['to']}: {g['km']:.0f} km of {g['class']} drawn straight, as no route "
                          f"was found ({g['flags']})", title="No route found", mode=g["class"], km=g["km"],
                          why=g["flags"], **ends)
        elif g["router"].startswith("car") and g["class"] in ("cycled", "predicted"):
            yield finding("straight", g["a"], g["b"], p[1], p[2],
                          f"{g['from']} to {g['to']}: {g['km']:.0f} km of {g['class']} routed as a car, as the "
                          "bike route failed", title="Bike leg routed as a car", mode=g["class"], km=g["km"], **ends)
        elif g["class"] == "flight" and g["km"] < C.short_flight_km:
            yield finding("straight", g["a"], g["b"], p[1], p[2], f"{g['from']} to {g['to']}: a flight of only "
                          f"{g['km']:.0f} km", title="Short flight", mode="flight", km=g["km"], **ends)


def along(points, i, direction, far):
    """The point far km along the route from points[i], going forwards (1) or back (-1), or None at its end."""
    done, j = 0, i
    while 0 <= j + direction < len(points):
        done += distance_km(*points[j][1:3], *points[j + direction][1:3])
        j += direction
        if done >= far:
            return points[j]
    return None


def nearest_on(a, b, p):
    """(distance in km, (lat, lon)): the point on the straight line from a to b nearest p, all (lat, lon)."""
    flat = Flat(p[0])
    (ax, ay), (bx, by), (px, py) = (flat.xy(*q) for q in (a, b, p))
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    x, y = ax + t * dx, ay + t * dy
    return math.hypot(px - x, py - y), (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def arm(points, i, direction):
    """The route's (lat, lon)s from points[i] going one way, up to checks.spike_max_km along it."""
    line, done, j = [points[i][1:3]], 0, i
    while 0 <= j + direction < len(points) and done < C.spike_max_km:
        done += distance_km(*points[j][1:3], *points[j + direction][1:3])
        j += direction
        line.append(points[j][1:3])
    return line


def spike_base(points, i):
    """(lat, lon) of the base of a spike to points[i]: where the route's way out and way back part,
    following the way out back from spike_km while it's within spike_join_km of the way back."""
    out, back = arm(points, i, -1), arm(points, i, 1)
    done, base = 0, None
    for p, q in zip(out, out[1:]):
        done += distance_km(*p, *q)
        if done < C.spike_km:
            continue
        gap, on_back = min(nearest_on(a, b, q) for a, b in zip(back, back[1:]))
        if gap > C.spike_join_km:
            break
        base = ((q[0] + on_back[0]) / 2, (q[1] + on_back[1]) / 2)
    return base


def own_row(places, p):
    """The id of the known place with its own lat,lon, at a UTC time, that is route point p, or None."""
    for r in places:
        if not (r.get("lat") and r.get("lon") and r["time"].endswith("Z")):
            continue
        try:
            t = datetime.fromisoformat(f"{r['start_date']}T{r['time'][:-1]}").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if abs(t - p[0]) <= timedelta(minutes=2) and distance_km(float(r["lat"]), float(r["lon"]), p[1], p[2]) < 0.002:
            return r["id"]
    return None


def check_spikes(route, places):
    last = None
    for i, p in enumerate(route.points):
        if p[4] not in FIXED:
            continue
        before, after = along(route.points, i, -1, C.spike_km), along(route.points, i, 1, C.spike_km)
        if (before and after and distance_km(*before[1:3], *after[1:3]) < C.spike_apart_km
                and after[0] - before[0] < timedelta(hours=C.spike_hours)
                and distance_km(*before[1:3], *p[1:3]) > C.spike_km / 2):
            if not (last and distance_km(*last[1:3], *p[1:3]) < C.spike_apart_km
                    and p[0] - last[0] < timedelta(hours=C.spike_hours)):
                to = spike_base(route.points, i) or nearest_on(before[1:3], after[1:3], p[1:3])[1]
                m = move(p, to, places)
                yield finding("spike", before[0], after[0], p[1], p[2],
                              f"the route goes out to this {p[4].replace('_', ' ')} ({p[0]:%H:%M}Z) and straight back, "
                              f"{m['km']:.1f} km from the route either side",
                              title=f"Out to a {p[4].replace('_', ' ')} and straight back",
                              fix={"action": "move", "move": m}, point=p[4], at_utc=stamp(p[0]), km=m["km"])
            last = p


def check_detours(route):
    for g in route.legs:
        if g["router"] != "straight" and g["straight"] >= C.detour_km and g["km"] > C.detour * g["straight"]:
            p = route.at(g["a"])
            yield finding("detour", g["a"], g["b"], p[1], p[2],
                          f"{g['from']} to {g['to']}: {g['km']:.0f} km routed for {g['straight']:.0f} km in a straight line",
                          km=g["km"], straight_km=g["straight"], factor=round(g["km"] / g["straight"], 1),
                          router=g["router"], **{"from": g["from"], "to": g["to"]})


def check_unused(route, places):
    """Known places with their own lat,lon that aren't points of the route."""
    used = {(f"{p[1]:.6f}", f"{p[2]:.6f}") for p in route.points if p[4] == "known_place"}
    recorded = [p[0] for p in route.points if p[4] == "recorded"]
    seen = set()
    for r in places:
        if not (r.get("lat") and r.get("lon")) or r["feature"] != "given":
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        if (f"{lat:.6f}", f"{lon:.6f}") in used:
            continue
        text = (r["time"] or "12:00:00").rstrip("Z")
        try:
            t = datetime.fromisoformat(f"{r['start_date']}T{text}").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        key = (r["start_date"], r["time"], r["note"])
        if key in seen:
            continue
        seen.add(key)
        group = [o for o in places if (o["start_date"], o["time"], o["note"]) == key and o.get("lat") and o.get("lon")]
        why = ("a ride was recorded within an hour either side of it, and is used instead"
               if r["time"].endswith("Z") and inside_ride(recorded, t)
               else "another point at the same time replaces it, or it's inside a ride")
        what = f"{len(group)} known places at {r['time'] or r['start_date']}" if len(group) > 1 else "the known place"
        yield finding("unused_point", t, t, lat, lon,
                      f"{what} {r['note'] or r['town']!r} {'are' if len(group) > 1 else 'is'}n't on the route: {why}",
                      rows={"known_places": [o["id"] for o in group]}, fix={"action": "remove_places"},
                      places=len(group), note=r["note"] or r["town"], why=why)


# Crossings: rivers ridden over with no bridge in OSM

CELL = 0.01  # degrees: the grid OSM segments are indexed on, about 1 km


def cells_along(a, b, margin=True):
    """The grid cells a line from a to b (lat, lon) passes through, and with margin their neighbours."""
    n = max(1, math.ceil(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / (CELL / 2)))
    found = set()
    for k in range(n + 1):
        lat, lon = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
        i, j = math.floor(lat / CELL), math.floor(lon / CELL)
        if margin:
            found.update((i + di, j + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1))
        else:
            found.add((i, j))
    return found


def kind_of(tags, geometry):
    if geometry == "Point":
        return "ford" if tags.get("ford", "no") != "no" else None
    if tags.get("waterway") in C.waterways and "tunnel" not in tags:
        return "water"
    if "highway" in tags and tags.get("bridge", "no") != "no":
        return "bridge"
    if "highway" in tags and tags.get("ford", "no") != "no":
        return "ford"
    return None


def read_osm(near):
    """(features, index): features are (kind, tags, [(lat, lon), ...]); the index maps
    (kind, cell) to [(feature, segment), ...] for the segments in cells in near."""
    features, index = [], defaultdict(list)
    # Whole degrees near the track: most features are nowhere near it, and this is a cheap first test
    degrees = {(math.floor(i * CELL), math.floor(j * CELL)) for i, j in near}
    with WATERWAYS.open(encoding="utf-8") as f:
        for line in f:
            feature = json.loads(line.lstrip("\x1e"))
            geometry, tags = feature["geometry"], feature["properties"]
            kind = kind_of(tags, geometry["type"])
            if not kind:
                continue
            coords = geometry["coordinates"]
            line_ = [(lat, lon) for lon, lat in ([coords] if geometry["type"] == "Point" else coords)]
            if not any((math.floor(lat), math.floor(lon)) in degrees for lat, lon in line_):
                continue
            hits = []
            for s, (p, q) in enumerate(zip(line_, line_[1:] or line_)):
                cells = {c for c in cells_along(p, q, margin=False) if c in near}
                hits.extend(((kind, c), s) for c in cells)
            if hits:
                for key, s in hits:
                    index[key].append((len(features), s))
                features.append((kind, tags, line_))
    return features, index


def intersection(p, q, r, s):
    """(t along pq, (x, y)) where segment pq crosses segment rs, or None."""
    dx, dy, ex, ey = q[0] - p[0], q[1] - p[1], s[0] - r[0], s[1] - r[1]
    den = dx * ey - dy * ex
    if den == 0:
        return None
    t = ((r[0] - p[0]) * ey - (r[1] - p[1]) * ex) / den
    u = ((r[0] - p[0]) * dy - (r[1] - p[1]) * dx) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t, (p[0] + t * dx, p[1] + t * dy)
    return None


def segments(index, kind, cells):
    """The (feature, segment) pairs of kind in cells, once each."""
    return {fs for c in cells for fs in index.get((kind, c), ())}


def crossing_at(features, index, p, q):
    """(lat, lon, feature) of the first waterway the step from p to q crosses, or None."""
    flat = Flat(*p)
    a, b = flat.xy(*p), flat.xy(*q)
    best = None
    for f, s in segments(index, "water", cells_along(p, q)):
        line = features[f][2]
        hit = intersection(a, b, flat.xy(*line[s]), flat.xy(*line[s + 1]))
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], hit[1], f)
    return (*flat.latlon(*best[1]), best[2]) if best else None


def classify(features, index, lat, lon, water):
    """bridge, ford or boat? for a crossing at lat, lon of the waterway feature water."""
    flat = Flat(lat, lon)
    near = cells_along((lat, lon), (lat, lon))
    name = features[water][1].get("name")
    same = [f for f, _ in segments(index, "water", near)
            if f == water or (name and features[f][1].get("name") == name)]
    for kind in ("bridge", "ford"):
        for f, s in segments(index, kind, near):
            line = features[f][2]
            if len(line) == 1:  # a ford node
                if distance_km(lat, lon, *line[0]) <= C.bridge_m / 1000:
                    return kind
                continue
            r, t = flat.xy(*line[s]), flat.xy(*line[s + 1])
            for w in same:
                wline = features[w][2]
                for u, v in zip(wline, wline[1:]):
                    hit = intersection(r, t, flat.xy(*u), flat.xy(*v))
                    if hit and math.hypot(*hit[1]) <= C.bridge_m / 1000:
                        return kind
    return "boat?"


def check_crossings(points):
    """Steps of a ride (up to route.gap_km) crossing a waterway's centre line with no bridge or ford
    within checks.bridge_m, over a stop of checks.crossing_min or more: likely boats. Rivers missing
    from OSM are missed, and bridges missing from it give false ones."""
    if not WATERWAYS.exists():
        print(f"no {WATERWAYS.name} (make osm), so no crossings")
        return

    def moving(i, j):
        h = max((points[j][0] - points[i][0]).total_seconds() / 3600, 1 / 60)
        return distance_km(*points[i][1:], *points[j][1:]) / h > C.moving_kmh

    def span(i):
        """(start, end) fixes of a crossing over the step from fix i: back and forward through any stop."""
        start, end = i, i + 1
        while start > 0 and not moving(start - 1, start):
            start -= 1
        while end < len(points) - 1 and not moving(end, end + 1):
            end += 1
        return start, end

    steps = [i for i in range(len(points) - 1) if distance_km(*points[i][1:], *points[i + 1][1:]) <= GAP_KM]
    near = set()
    for i in steps:
        near |= cells_along(points[i][1:], points[i + 1][1:])
    features, index = read_osm(near)
    last = None
    for i in steps:
        found = crossing_at(features, index, points[i][1:], points[i + 1][1:])
        if not found:
            continue
        lat, lon, water = found
        kind = classify(features, index, lat, lon, water)
        if kind == "bridge":
            continue
        first, final = span(i)
        start, end = points[first][0], points[final][0]
        if (end - start).total_seconds() < C.crossing_min * 60 or last == (start, end):
            continue  # ridden through; or the same stop on both sides (braided channels)
        last = (start, end)
        tags = features[water][1]
        river = tags.get("name", "")
        mode = "hike" if kind == "ford" else "ferry"
        yield finding("crossing", start, end, lat, lon, f"{kind} {river or tags.get('waterway', '')}",
                      title="Ford" if kind == "ford" else "Boat across a river?",
                      fix=label_fix(start, end, mode, f"across the {river}" if river else ""),
                      waterway=tags.get("waterway", ""), river=river, kind=kind,
                      minutes=round((end - start).total_seconds() / 60))


def check_suggestions(points):
    """Komoot hikes, lifts during them (faster than walk_kmh), and buses or lifts anywhere else
    (faster than vehicle_kmh for vehicle_min), from speeds over windows of window_min."""
    hikes = [(when(r["start_utc"]), when(r["end_utc"]), r["name"]) for r in rows(KOMOOT_TOURS) if r["sport"] == "hike"]

    def windows():
        found, i = [], 0
        while i < len(points) - 1:
            j, dist = i, 0
            while (j < len(points) - 1 and points[j][0] - points[i][0] < timedelta(minutes=C.window_min)
                   and points[j + 1][0] - points[j][0] <= timedelta(minutes=C.window_gap_min)):
                dist += distance_km(*points[j][1:], *points[j + 1][1:])
                j += 1
            if j == i:  # a gap follows
                i += 1
                continue
            found.append((i, j, dist / ((points[j][0] - points[i][0]).total_seconds() / 3600)))
            i = j
        return found

    def runs(wins, test):
        found = []
        for i, j, kmh in wins:
            if not test(i, kmh):
                continue
            if found and found[-1][1] == i:
                found[-1][1] = j
            else:
                found.append([i, j])
        return found

    def speed(i, j):
        h = (points[j][0] - points[i][0]).total_seconds() / 3600
        dist = sum(distance_km(*points[k][1:], *points[k + 1][1:]) for k in range(i, j))
        return dist, dist / h if h else 0

    def suggest(i, j, mode, why, title, **facts):
        mid = points[(i + j) // 2]
        dist, kmh = speed(i, j)
        return (points[i][0], points[j][0],
                finding("suggestion", points[i][0], points[j][0], mid[1], mid[2], f"{mode}: {why}", title=title,
                        fix=label_fix(points[i][0], points[j][0], mode, why), mode=mode, km=round(dist, 1),
                        kmh=round(kmh), **facts))

    wins = windows()
    found = []
    for start, end, tour in hikes:
        inside = [k for k, p in enumerate(points) if start <= p[0] <= end]
        if not inside:
            continue
        lifts = runs([w for w in wins if inside[0] <= w[0] and w[1] <= inside[-1]], lambda i, kmh: kmh > C.walk_kmh)
        for k in range(len(lifts) - 1, 0, -1):
            if points[lifts[k][0]][0] - points[lifts[k - 1][1]][0] <= timedelta(minutes=C.lift_join_min):
                lifts[k - 1][1] = lifts.pop(k)[1]
        walked = inside[0]
        for i, j in lifts:
            if i > walked:
                found.append(suggest(walked, i, "hike", f"Komoot hike: {tour}", "Komoot hike", tour=tour))
            found.append(suggest(i, j, "car", f"a lift on the hike {tour}", "Lift on a hike", tour=tour,
                                 limit_kmh=C.walk_kmh))
            walked = j
        if walked < inside[-1]:
            found.append(suggest(walked, inside[-1], "hike", f"Komoot hike: {tour}", "Komoot hike", tour=tour))

    def hike_at(i):
        return any(h[0] <= points[i][0] <= h[1] for h in hikes)

    for i, j in runs(wins, lambda i, kmh: kmh > C.vehicle_kmh and not hike_at(i)):
        if points[j][0] - points[i][0] >= timedelta(minutes=C.vehicle_min):
            found.append(suggest(i, j, "car", "a bus or a lift?", "Too fast for a bike", limit_kmh=C.vehicle_kmh))
    for *_, f in sorted(found, key=lambda x: (x[0], x[1])):
        yield f


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    if not (ROUTE / "route.csv").exists():
        sys.exit(f"{ROUTE / 'route.csv'} is missing: run make route")
    route = Route()
    tracks = read_gpx()
    modes = read_modes(MODES_CSV)
    places = rows(PLACES_CSV)
    track = [(when(r["utc"]), float(r["lat"]), float(r["lon"])) for r in rows(TRACK_POINTS)]
    found = [*check_unlabelled(route), *check_gpx(route, tracks), *check_rows(route, modes),
             *check_switches(tracks), *check_speeds(route, modes, places), *check_days(tracks),
             *check_straight(route), *check_spikes(route, places), *check_detours(route),
             *check_unused(route, places), *check_crossings(track), *check_suggestions(track)]
    ok = rows(DISMISSED_CSV)
    for f in found:
        if by := next((r for r in ok if dismisses(r, f)), None):
            f["dismissed"] = by["id"]
    found.sort(key=lambda f: (f["start_utc"], f["end_utc"], f["check"]))
    write_json(FINDINGS, found, indent=None)
    counts = Counter(f["check"] for f in found if "dismissed" not in f)
    print(f"route.gpx: {len(tracks)} tracks, {sum(len(p) for _, p in tracks)} points")
    for check in TITLES:
        print(f"  {counts.get(check, 0):4d}  {check}")
    dismissed = sum(1 for f in found if "dismissed" in f)
    print(f"{sum(counts.values())} findings to look at in the review app's Route view, {dismissed} dismissed. "
          "Crossings and suggestions a travel mode row already covers count as done there")


if __name__ == "__main__":
    main()
