#!/usr/bin/env python3
"""The whole trip as one route: recorded rides, with the gaps between them routed.

Usage: route.py

Anchors are the recorded points (make track), the known places (make places) and the photos
with GPS (make index) taken between rides, except those in manual/ignored_photos.csv
(file,note): their GPS is wrong. Where two anchors in a row are more than route.gap_km apart,
the gap between them is a leg, routed along OSM roads by Valhalla, from the tiles make osm
builds. manual/travel_modes.csv (id,start,end,mode,note; UTC YYYY-MM-DD or YYYY-MM-DDTHH:MM)
says how stretches were travelled: a gap leg takes a row's mode if the row lies inside it or
covers most of it, and a recorded point inside a row's time takes its mode too (a boat across a
river, mid-ride). Other gaps are taken as cycled. See docs/route.md.

manual/stays.csv (the Stays view) gives where each stay of several nights was: you're there from
route.stay_arrive on the first night to route.stay_leave on the morning of leaving, and over
every night in between, as for a known place with its own lat,lon. One of those points is left
out where a photo, ride or known place close in time is too far away to have reached it: you came
in later or left earlier. A stay's nights are stops (class stopped), whatever travel mode row
takes them in.

Each stretch of the route has a class:
  cycled     recorded, or a gap with a cycled row
  predicted  a routed gap with no row, taken as cycled
  stopped    a step that goes nowhere
  <mode>     a gap or recorded stretch with a row of another mode (settings.yaml, modes)

Writes, in processing/route:
  route.csv      utc,lat,lon,class,mode,source,ref; times in gaps are spread by distance between
                 the anchors on either side. ref names an anchor's row: a known place's id, a
                 stay's id, a photo's file
  legs.csv       one row per gap leg: its ends, km, class, router, the travel mode rows' notes
                 (mode_note), and what looks wrong (flags)
  unlabelled.csv runs of legs and hops still predicted
  route.geojson  one LineString per run of a class, for the map
  route.gpx      the same runs as tracks, with the class as their <type>
  stats.csv      km per class by month, by country and in total
  route.png      the route coloured by class, to check by eye
"""
import argparse
import bisect
import json
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from common.geo import distance_km, kmh, length_km as length
from common.tables import read_rows as rows, write_rows, write_text
from common.times import exif_time, local_offsets, parse, place_time, stamp
from common.towns import Towns
from repo import (IGNORED_PHOTOS_CSV, INDEX, MODES_CSV, PLACES_CSV, ROUTE, STAYS_CSV, TRACK_POINTS,
                  VALHALLA_CONFIG)
from settings import settings

R = settings.route
# Valhalla's costing for each router profile, and options to tune it with
COSTING = {"bike": "bicycle", "car": "auto", "foot": "pedestrian"}
COSTING_OPTIONS = {"bicycle": {"bicycle_type": R.bicycle_type, "use_roads": R.use_roads}}
GAP_KM = R.gap_km
STILL_KM = R.still_km
FAST_DAY_KM, FAST_KMH = 120, 30  # a cycled or predicted leg longer than this per day, or faster, is flagged
# Each mode's router profile; None is a straight line
MODES = {m: (None if v.router == "none" else v.router) for m, v in settings.modes.items()}
CLASSES = settings.classes


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# The row each anchor came from, by (utc, lat, lon, source): a known place's or stay's id, a photo's
# file. route.csv gives it as ref, for the review app
REFS = {}


def nightly(first, last, offsets):
    """UTC times of a stay from the evening of first to the morning of last: there every night."""
    days = [str(first + timedelta(days=i)) for i in range((last - first).days + 1)]
    return [place_time(day, hhmm, offsets) for day in days for hhmm in (R.stay_leave, R.stay_arrive)][1:-1]


def read_stays(offsets):
    """(start, end, lat, lon, town, id, nights) per stay in manual/stays.csv, nights the UTC times
    it's there: route.stay_arrive on the first night to route.stay_leave on leaving, every night."""
    from openlocationcode import openlocationcode as olc
    if not STAYS_CSV.exists():
        sys.exit(f"{STAYS_CSV} is missing: check the stays in the review app (make review), which saves it")
    found = []
    for n, r in enumerate(rows(STAYS_CSV), start=2):
        try:
            first, leaving = date.fromisoformat(r["first_night"]), date.fromisoformat(r["leaving"])
        except (KeyError, ValueError):
            sys.exit(f"{STAYS_CSV}:{n}: first_night and leaving must be YYYY-MM-DD")
        if leaving <= first:
            sys.exit(f"{STAYS_CSV}:{n}: leaving {leaving} isn't after the first night {first}")
        code = (r["plus_code"] or "").strip().upper()
        if not olc.isFull(code):
            print(f"warning: {STAYS_CSV}:{n}: the stay in {r['town']} from {first} has no full plus code; left out")
            continue
        area = olc.decode(code)
        nights = nightly(first, leaving, offsets)
        found.append((nights[0], nights[-1], area.latitudeCenter, area.longitudeCenter, r["town"], r["id"], nights))
    return found


def anchors(stays, offsets):
    """Time-sorted (utc, lat, lon, source, name) of recorded points, stays, known places and photos.

    Each night of a stay is an anchor at route.stay_leave and route.stay_arrive, like a known
    place with its own lat,lon; one of those at the same time replaces it, and it replaces a
    looked-up one.

    Known places' times are local, made UTC with the offset of the ride or photo nearest in
    time, unless they end in Z. A place covering several days is reached at stay_arrive on the
    first and left at stay_leave on the last, and one with its own lat,lon is there every night
    in between; a single day without a time is route.midday. Known places and photos inside a
    ride are left out, as the ride says where you were.
    """
    recorded = [(parse(r["utc"]), float(r["lat"]), float(r["lon"]), "recorded", "") for r in rows(TRACK_POINTS)]
    times = [p[0] for p in recorded]
    candidates = []
    for r in rows(PLACES_CSV):
        if not r["lat"]:
            continue
        first, last = r["start_date"], r["end_date"] or r["start_date"]
        if r["time"]:
            whens = [place_time(first, r["time"], offsets)]
        elif first == last:
            whens = [place_time(first, R.midday, offsets)]
        elif r["feature"] != "given":
            whens = [place_time(first, R.stay_arrive, offsets), place_time(last, R.stay_leave, offsets)]
        else:
            # Every night of a stay at a point of your own, so days out from it run out and back,
            # not across the night. A looked-up town's centre could be far from where you slept
            whens = nightly(date.fromisoformat(first), date.fromisoformat(last), offsets)
        for when in whens:
            candidates.append((when, float(r["lat"]), float(r["lon"]), r["geoname"] or r["town"],
                               r["feature"] == "given", r["id"]))
    near = timedelta(minutes=R.replace_min)
    own = [c[0] for c in candidates if c[4]]
    nights = []
    for *_, lat, lon, town, stay_id, whens in stays:
        for when in whens:
            if not inside_ride(times, when) and not any(abs(g - when) <= near for g in own):
                nights.append((when, lat, lon, "stay", town))
                REFS[(when, lat, lon, "stay")] = stay_id
    given = own + [n[0] for n in nights]
    places = []
    for when, lat, lon, name, is_given, place_id in candidates:
        if not inside_ride(times, when) and (is_given or not any(abs(g - when) <= near for g in given)):
            places.append((when, lat, lon, "known_place", name))
            REFS[(when, lat, lon, "known_place")] = place_id
    found = sorted(recorded + nights + places, key=lambda p: p[0])
    photos = [p for p in photo_points(recorded, given) if found[0][0] <= p[0] <= found[-1][0]]
    return drop_stay_conflicts(drop_spikes(sorted(found + photos, key=lambda p: p[0])))


def bad_fix(recorded, times, photo):
    """Whether a photo is further from a recorded fix within route.fix_min than route.fix_kmh allows."""
    i = bisect.bisect_left(times, photo[0])
    for j in (i - 1, i):
        if 0 <= j < len(times) and abs(times[j] - photo[0]) <= timedelta(minutes=R.fix_min):
            hours = max(abs((times[j] - photo[0]).total_seconds()) / 3600, 1 / 60)
            if distance_km(*recorded[j][1:3], *photo[1:3]) / hours > R.fix_kmh:
                return True
    return False


def photo_points(recorded, given):
    """(utc, lat, lon, "photo", "") of photos with a GPS time and position outside rides: the
    first and last of each run of photos within route.photo_km of the run's first, so a stop gives
    its arrival and departure. Photos with a bad fix are left out, with every other photo at
    exactly the same position, and so are photos a known place at given times replaces."""
    ignored = {Path(r["file"].strip()).name for r in rows(IGNORED_PHOTOS_CSV)}
    indexed = rows(INDEX / "photos.csv")
    skipped = [r["file"] for r in indexed if Path(r["file"]).name in ignored]
    if skipped:
        print(f"left out {len(skipped)} photo{'s' if len(skipped) > 1 else ''} listed in {IGNORED_PHOTOS_CSV.name}")
    times = [p[0] for p in recorded]
    files = {}
    photos = []
    for r in indexed:
        if r["gps_time"] and r["lat"] and r["lon"] and Path(r["file"]).name not in ignored:
            p = (exif_time(r["gps_time"]).replace(tzinfo=timezone.utc), float(r["lat"]), float(r["lon"]))
            photos.append(p)
            files.setdefault(p, r["file"])
    photos.sort()
    bad = {p[1:] for p in photos if bad_fix(recorded, times, p)}
    left_out = [p for p in photos if p[1:] in bad]
    for spot in sorted(bad, key=lambda b: min(p[0] for p in left_out if p[1:] == b)):
        at = [p[0] for p in left_out if p[1:] == spot]
        print(f"left out {len(at)} photo{'s' if len(at) > 1 else ''} at {spot[0]:.5f},{spot[1]:.5f} "
              f"{min(at):%Y-%m-%d %H:%M}: too far from a ride minutes away, a bad GPS fix")
    near = timedelta(minutes=R.replace_min)
    runs = []
    for p in photos:
        if inside_ride(times, p[0]) or p[1:] in bad or any(abs(g - p[0]) <= near for g in given):
            continue
        if runs and distance_km(*runs[-1][0][1:], *p[1:]) <= R.photo_km:
            runs[-1].append(p)
        else:
            runs.append([p])
    kept = [p for run in runs for p in ([run[0], run[-1]] if len(run) > 1 else run)]
    for p in kept:
        REFS[(*p, "photo")] = files[p]
    return [(*p, "photo", "") for p in kept]


def drop_spikes(points):
    """points without the photos that are faster than route.spike_kmh from their neighbours on both sides."""
    kept = [p for i, p in enumerate(points)
            if not (p[3] == "photo" and 0 < i < len(points) - 1
                    and kmh(points[i - 1], p) > R.spike_kmh and kmh(p, points[i + 1]) > R.spike_kmh)]
    for p in sorted(set(points) - set(kept)):
        print(f"left out a photo at {p[1]:.4f},{p[2]:.4f} {p[0]:%Y-%m-%d %H:%M}: too far from the route either side")
    return kept


def drop_stay_conflicts(points):
    """points without the stay points (evening and morning, local) that the evidence nearest them
    in time says you weren't at: a photo, ride or known place within route.stay_hours that's more
    than route.stay_kmh and route.gap_km away. You came in later or left earlier, and the stay's
    next or last point still holds you there."""
    window = timedelta(hours=R.stay_hours)
    evidence = [p for p in points if p[3] != "stay"]
    times = [p[0] for p in evidence]
    kept = []
    for p in points:
        if p[3] == "stay":
            i = bisect.bisect_left(times, p[0])
            near = [e for e in evidence[max(i - 1, 0):i + 1] if abs(e[0] - p[0]) <= window]
            clash = [e for e in near if kmh(e, p) > R.stay_kmh and distance_km(e[1], e[2], p[1], p[2]) > GAP_KM]
            if clash:
                e = min(clash, key=lambda e: abs(e[0] - p[0]))
                print(f"left out the {p[4]} stay's point at {p[0]:%Y-%m-%d %H:%M}Z: a {e[3]} at {e[0]:%H:%M}Z "
                      f"is {distance_km(e[1], e[2], p[1], p[2]):.0f} km away")
                continue
        kept.append(p)
    return kept


def inside_ride(times, when):
    """Whether recorded points lie within route.inside_hours on both sides of when."""
    i = bisect.bisect_left(times, when)
    near = timedelta(hours=R.inside_hours)
    return 0 < i < len(times) and when - times[i - 1] <= near and times[i] - when <= near


def read_modes(path=MODES_CSV):
    """(start, end, mode, note, id) per row of manual/travel_modes.csv; a date alone covers its whole day."""
    found = []
    for n, r in enumerate(rows(path), start=2):
        if r["mode"] not in MODES:
            sys.exit(f"{path}:{n}: mode {r['mode']!r} isn't one of {' '.join(MODES)}")
        start = utc(r["start"])
        end = utc(r["end"] or r["start"])
        if "T" not in (r["end"] or r["start"]):
            end += timedelta(days=1)
        found.append((start, end, r["mode"], r.get("note") or "", r.get("id", "")))
    return found


_actor = None


def actor():
    """Valhalla, loaded once."""
    global _actor
    if _actor is None:
        if not VALHALLA_CONFIG.exists():
            sys.exit(f"{VALHALLA_CONFIG} is missing: run make osm")
        import valhalla
        config = json.loads(VALHALLA_CONFIG.read_text())
        config["logging"]["type"] = ""  # not a line for every route
        _actor = valhalla.Actor(config)
    return _actor


def decode(shape):
    """[(lat, lon), ...] from a Valhalla shape: an encoded polyline with 6 decimals."""
    line, values, i = [], [0, 0], 0
    while i < len(shape):
        for k in range(2):
            result, shift = 0, 0
            while True:
                b = ord(shape[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            values[k] += ~(result >> 1) if result & 1 else result >> 1
        line.append((values[0] / 1e6, values[1] / 1e6))
    return line


def route(profile, a, b):
    """[(lat, lon), ...] from a to b, or (None, why) if the router has no sensible route."""
    costing = COSTING[profile]
    request = {"locations": [{"lat": p[1], "lon": p[2], "search_cutoff": R.snap_km * 1000} for p in (a, b)],
               "costing": costing, "costing_options": COSTING_OPTIONS, "directions_type": "none"}
    try:
        data = actor().route(request)
    except RuntimeError as e:  # no road near an end, or no path: the message is JSON
        try:
            why = json.loads(str(e)).get("error", str(e))
        except ValueError:
            why = str(e)
        return None, f"no {profile} route ({why})"
    line = [p for leg in data["trip"]["legs"] for p in decode(leg["shape"])]
    straight = distance_km(a[1], a[2], b[1], b[2])
    if length(line) > R.detour_factor * straight + R.detour_km:
        return None, f"{profile} route is a {length(line):.0f} km detour"
    return line, ""


def thinned(line):
    kept = [line[0]]
    for p in line[1:-1]:
        if distance_km(*kept[-1], *p) >= R.spacing_km:
            kept.append(p)
    return kept + [line[-1]]


def covers(row, a, b):
    """Whether a travel mode row is part of a leg from a to b: inside it, or most of its time.

    Rows given by date run all day, so a bare overlap would also take in the
    rides before and after them.
    """
    start, end = row[:2]
    if b[0] - a[0] < timedelta(minutes=1):  # a step in no time (to the minute): the row's time takes it in
        return start <= a[0] <= end
    overlap = min(end, b[0]) - max(start, a[0])
    return (a[0] <= start and end <= b[0]) or overlap > (b[0] - a[0]) / 2


def leg_mode(a, b, modes):
    """(mode, note, warning) of the travel mode rows that are part of a leg from a to b."""
    over = [t for t in modes if covers(t, a, b)]
    if not over:
        return None, "", ""
    warnings = []
    if len({t[2] for t in over}) > 1:
        warnings.append("rows with different modes overlap it")
    if b[0] - a[0] > timedelta(days=1) and not any(t[0] <= a[0] and b[0] <= t[1] for t in over):
        warnings.append("over a day long and only partly covered by a travel mode: add known places to split it")
    return over[0][2], "; ".join(t[3] for t in over if t[3]), "; ".join(warnings)


def point_mode(when, modes):
    """The mode of the first row whose time takes in when, or None."""
    return next((t[2] for t in modes if t[0] <= when <= t[1]), None)


def gap_leg(a, b, modes):
    """(line, class, travel mode, router, the rows' note, flags) for a gap from anchor a to b."""
    mode, note, warning = leg_mode(a, b, modes)
    notes = [warning] if warning else []
    profile = MODES[mode] if mode else "bike"
    line, router = None, "straight"
    if profile:
        line, why = route(profile, a, b)
        if line is None and profile == "bike":
            notes.append(why)
            line, why = route("car", a, b)
            router = "car, as bike failed"
        else:
            router = profile
        if line is None:
            notes.append(why)
            router = "straight"
    ends = [(a[1], a[2]), (b[1], b[2])]
    line = ends[:1] + thinned(line)[1:-1] + ends[1:] if line else ends
    return line, mode or "predicted", mode or "", router, note, notes


def leg_km(leg):
    return leg["km"] if leg["gap"] else leg["straight"]


def unlabelled(legs):
    """Runs of legs and hops still predicted (not recorded, labelled or a stop), each a list of legs."""
    found = []
    for leg in legs:
        if leg["class"] != "predicted":
            continue
        if found and found[-1][-1]["b"][0] == leg["a"][0] and found[-1][-1]["b"][1:3] == leg["a"][1:3]:
            found[-1].append(leg)
        else:
            found.append([leg])
    return found


def place_name(towns, anchor):
    """A known place's own name, or the nearest town to a recorded point."""
    _, lat, lon, _, name = anchor
    if name:
        return name
    town = towns.nearest(lat, lon)
    return f"{town[0]} ({town[1]})" if town else f"{lat:.3f},{lon:.3f}"


def build(points, modes, towns):
    """The route as a list of legs: dicts with the anchors, line, times and class."""
    legs = []
    for a, b in zip(points, points[1:]):
        straight = distance_km(a[1], a[2], b[1], b[2])
        if straight <= GAP_KM:
            # A step between recorded points takes a row's mode if both its ends are inside that row's
            # time (a boat mid-ride); a hop between fixed points, a row's that's part of it, as a gap leg
            # does, or it's a stop if it goes nowhere
            both_recorded = a[3] == b[3] == "recorded"
            if both_recorded:
                mode = next((t[2] for t in modes if t[0] <= a[0] and b[0] <= t[1]), "")
                cls = mode or "cycled"
            elif straight < STILL_KM:
                mode, cls = "", "stopped"
            else:
                mode = next((t[2] for t in modes if covers(t, a, b)), "")
                cls = mode or "predicted"
            leg = {"a": a, "b": b, "line": [(a[1], a[2]), (b[1], b[2])], "class": cls, "mode": mode,
                   "gap": False, "straight": straight}
            if cls == "predicted":  # named only where it's needed: the report of what's unlabelled
                leg.update({"from": place_name(towns, a), "to": place_name(towns, b)})
            legs.append(leg)
            continue
        line, cls, mode, router, note, notes = gap_leg(a, b, modes)
        km, hours = length(line), (b[0] - a[0]).total_seconds() / 3600
        days = (b[0].date() - a[0].date()).days + 1  # each day touched could have a ride in it
        if cls in ("predicted", "cycled") and km > 10 and (km > FAST_DAY_KM * days or (hours < 12 and km / max(hours, 0.01) > FAST_KMH)):
            notes.insert(0, "fast for a bike")
        legs.append({"a": a, "b": b, "line": line, "class": cls, "mode": mode, "gap": True,
                     "router": router, "mode_note": note, "notes": notes, "km": km, "straight": straight, "hours": hours,
                     "from": place_name(towns, a), "to": place_name(towns, b)})
    for leg in legs:
        leg["times"] = spread(leg["a"][0], leg["b"][0], leg["line"])
    return legs


def spread(start, end, line):
    """A time for each point of line, by distance along it from start to end."""
    total = length(line)
    times, done = [start], 0
    for p, q in zip(line, line[1:]):
        done += distance_km(*p, *q)
        times.append(start + (end - start) * (done / total if total else 1))
    return times


def route_rows(legs, modes):
    """utc,lat,lon,class,mode,source,ref per point; each leg's first point is the last one's end.

    A recorded point is cycled, or the mode of a row its time is inside.
    """
    def end_row(p, leg):
        ref = REFS.get(p[:4], "")
        if p[3] == "recorded":
            mode = point_mode(p[0], modes) or ""
            return [p[0], p[1], p[2], mode or "cycled", mode, p[3], ref]
        return [p[0], p[1], p[2], leg["class"], leg["mode"], p[3], ref]

    out = [end_row(legs[0]["a"], legs[0])]
    for leg in legs:
        source = "routed" if leg["gap"] and leg["router"] != "straight" else "straight"
        for t, (lat, lon) in list(zip(leg["times"], leg["line"]))[1:-1]:
            out.append([t, lat, lon, leg["class"], leg["mode"], source, ""])
        out.append(end_row(leg["b"], leg))
    return out


def runs(legs):
    """Consecutive legs of the same class and mode, joined: (class, mode, times, line)."""
    found = []
    for leg in legs:
        key = (leg["class"], leg["mode"])
        if found and tuple(found[-1][:2]) == key:
            found[-1][2].extend(leg["times"][1:])
            found[-1][3].extend(leg["line"][1:])
        else:
            found.append([*key, list(leg["times"]), list(leg["line"])])
    return found


def stats(legs, towns):
    """km per class: (group, key) -> {class: km}."""
    countries, table = {}, {}
    for leg in legs:
        for t, p, q in zip(leg["times"], leg["line"], leg["line"][1:]):
            cell = (round(p[0], 1), round(p[1], 1))
            if cell not in countries:
                town = towns.nearest(*cell)
                countries[cell] = town[1] if town else "(none)"
            km = distance_km(*p, *q)
            for key in (("month", f"{t:%Y-%m}"), ("country", countries[cell]), ("total", "")):
                row = table.setdefault(key, dict.fromkeys(CLASSES, 0))
                row[leg["class"]] += km
    return table


def write_outputs(legs, modes, towns):
    write_rows(ROUTE / "route.csv", ["utc", "lat", "lon", "class", "mode", "source", "ref"],
               ([stamp(t), f"{lat:.6f}", f"{lon:.6f}", *rest] for t, lat, lon, *rest in route_rows(legs, modes)))

    write_rows(ROUTE / "legs.csv", ["start_utc", "end_utc", "hours", "from", "to", "straight_km", "routed_km",
                                    "class", "mode", "router", "mode_note", "flags"],
               ([stamp(g["a"][0]), stamp(g["b"][0]), f"{g['hours']:.1f}", g["from"], g["to"],
                 f"{g['straight']:.0f}", f"{g['km']:.0f}", g["class"], g["mode"], g["router"],
                 g["mode_note"], "; ".join(g["notes"])] for g in legs if g["gap"]))

    joined = runs(legs)
    features = [{"type": "Feature",
                 "properties": {"class": cls, "mode": mode, "start": stamp(times[0]), "end": stamp(times[-1]),
                                "km": round(length(line), 1)},
                 "geometry": {"type": "LineString", "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in line]}}
                for cls, mode, times, line in joined]
    write_text(ROUTE / "route.geojson", json.dumps({"type": "FeatureCollection", "features": features}))

    gpx = ET.Element("gpx", version="1.1", creator="route.py", xmlns="http://www.topografix.com/GPX/1/1")
    for cls, mode, times, line in joined:
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = f"{times[0]:%Y-%m-%d} {mode or cls}"
        ET.SubElement(trk, "type").text = cls
        seg = ET.SubElement(trk, "trkseg")
        for t, (lat, lon) in zip(times, line):
            pt = ET.SubElement(seg, "trkpt", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
            ET.SubElement(pt, "time").text = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = ROUTE / ".tmp.route.gpx"
    ET.ElementTree(gpx).write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(ROUTE / "route.gpx")

    table = stats(legs, towns)
    order = {"total": 0, "country": 1, "month": 2}
    write_rows(ROUTE / "stats.csv", ["group", "key", *(f"{c}_km" for c in CLASSES)],
               ([group, key, *(f"{row[c]:.0f}" for c in CLASSES)]
                for (group, key), row in sorted(table.items(), key=lambda kv: (order[kv[0][0]], kv[0][1]))))
    return joined, table[("total", "")]


def plot(joined):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colours = settings.colours
    style = {cls: dict(color=colours[cls], lw=0.8, ls="-" if cls in ("cycled", "ferry", "stopped") else
                       "--" if cls in ("predicted", "hike") else ":") for cls in CLASSES}
    style["stopped"]["lw"] = style["flight"]["lw"] = 0.5
    style["ferry"]["lw"] = 1.2
    fig, ax = plt.subplots(figsize=(8, 10))
    for cls, _, _, line in joined:
        ax.plot([p[1] for p in line], [p[0] for p in line], **style[cls])
    for cls in CLASSES:
        ax.plot([], [], label=cls, **style[cls])
    ax.legend(loc="lower left")
    # Zoomed to the bulk of the route, so a flight home doesn't shrink the rest
    lats = sorted(p[0] for *_, line in joined for p in line)
    lons = sorted(p[1] for *_, line in joined for p in line)
    for values, set_lim in ((lons, ax.set_xlim), (lats, ax.set_ylim)):
        low, high = values[len(values) // 200], values[-len(values) // 200 - 1]
        set_lim(low - 1, high + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    tmp = ROUTE / ".tmp.route.png"
    fig.savefig(tmp, dpi=150, bbox_inches="tight", format="png")
    tmp.replace(ROUTE / "route.png")


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    offsets = local_offsets()
    stays = read_stays(offsets)
    modes = read_modes()
    towns = Towns()
    legs = build(anchors(stays, offsets), modes, towns)
    joined, total = write_outputs(legs, modes, towns)
    plot(joined)
    left = unlabelled(legs)
    write_rows(ROUTE / "unlabelled.csv", ["start_utc", "end_utc", "km", "steps", "from", "to"],
               ([stamp(r[0]["a"][0]), stamp(r[-1]["b"][0]), f"{sum(leg_km(g) for g in r):.1f}", len(r),
                 r[0]["from"], r[-1]["to"]] for r in left))
    gaps = [g for g in legs if g["gap"]]
    print(f"{len(gaps)} gap legs; km " + ", ".join(f"{c} {total[c]:.0f}" for c in CLASSES))
    print(f"{len(left)} stretches still predicted, {sum(leg_km(g) for r in left for g in r):.0f} km: "
          "make check lists them with what else looks wrong" if left else "Nothing left unlabelled.")


if __name__ == "__main__":
    main()
