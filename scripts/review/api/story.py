"""The Story view's data: a story beside everything the trip left from its days.

A story's days are its Start time and Stop time in story_plans/*.csv (YY-MM-DD or YYYY-MM-DD, local
dates), widened by the view's padding.

  GET  /api/story/list                every story in the plans, with its dates
  GET  /api/story/STORY?pad=N         its days: route, legs, stays, photos, events, entries and the
                                      recorded rides: stats, an elevation profile, and where the
                                      markers and events fall on it
  GET  /api/story/STORY/text          raw/stories/STORY.md as it is (If-None-Match: 304 if unchanged)
  GET  /api/story/STORY/check         Claude's last suggestions for it, or null
  POST /api/story/STORY/check         ask Claude ({"model": "opus"|"sonnet"|"haiku"}) to compare the story
                                      with the sources: inconsistencies, details to add, answers to its
                                      {{notes}}; kept in processing/story/checks/
  POST /api/story/STORY/check/dismiss {"id": ..., "dismissed": true|false}
  GET  /api/story/entry/KIND/STEM     a diary entry: its text, audio and events

The story and the rides are only ever read. What this writes is Claude's suggestions.
"""
import bisect
import hashlib
import json
import os
import re
import threading
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote

from common.geo import distance_km
from common.llm import LimitReached, RetryableError, structured
from common.tables import read_rows as rows
from events import KINDS, entry_text
from repo import (BASE_DIR, COMPRESSED, EVENTS, GPX, IGNORED_PHOTOS_CSV, INDEX, LOCATED, RAW_STORIES, ROUTE,
                  STAYS_CSV, STORY_CHECKS, STORY_PLANS)
from shared import offsets as local_offsets, towns as cached_towns
from settings import settings
from store import Refused

PLANS = STORY_PLANS
STORIES = RAW_STORIES  # the stories as you write them, notes and all
PHOTOS = "clean/photos"
EXPORTED = BASE_DIR / PHOTOS / "darktable_exported"  # edited versions, under the same names
ROUTE_DIR = ROUTE
STAYS = STAYS_CSV
IGNORED = IGNORED_PHOTOS_CSV
CHECKS = STORY_CHECKS
COMPRESSED_DIR = COMPRESSED
GPX_DIR = GPX  # the recorded rides, only ever read
GPX_NS = "{http://www.topografix.com/GPX/1/1}"

# The ride stats beside the map
RIDE_GAP_S = 600          # points further apart in time than this are a pause in recording: no km between
RIDE_MOVING_KMH = 2.0     # slower than this counts as stopped, as Strava's moving time does
RIDE_SPEED_WINDOW_S = 20  # max speed is the fastest over this long
RIDE_MAX_KMH = 90         # faster than this is a GPS jump, not a descent
RIDE_SAMPLE_KM = 0.05     # the profile has a point at most this often...
RIDE_MAX_SAMPLES = 3000   # ...and at most this many points
RIDE_NEAR_KM = 1.0        # a marker this close to the ride, on its day, goes on the profile
RIDE_TOWN_KM = 3.0        # a town an event names counts as on the ride this close to it

MAX_PAD = 30          # days either side
SPACING_KM = 0.03     # recorded points closer together than this are thinned out, as on the review map
THUMB_PX = 400
MODELS = ("opus", "sonnet", "haiku")
PROMPT_BUDGET = 150_000  # characters of entry text sent to Claude; over it the longest are cut

CHECK_PROMPT = """\
You help the author of a travel book check a story against the sources. The book is about a \
two-year bicycle trip from Europe through West and Central Africa to South Africa. The author \
writes each story later, from memory, and wants to know where it disagrees with what was \
recorded at the time, and what from the time could make it richer.

You get the story as the author is writing it, with notes to self in {{double braces}}; then, \
for the story's days, a day-by-day summary of the route (from GPS, or routed between known \
points where there was none), the stays and the photos; the events indexed from the diary; and \
the diary entries themselves: spoken entries transcribed by machine (expect misheard names and \
words), written entries, blog posts and Komoot ride descriptions. Some are in French. An event's \
date marked (guessed) was worked out from the entry, not stated in it. Local times are worked \
out from the photos' clocks and can be an hour or more out, so don't rest an inconsistency on \
a time of day alone. Entries can recall days \
well before the day they were made.

Give suggestions of three kinds:
- inconsistency: the story states something the sources contradict or make unlikely: a date, a \
day count, a distance, a duration, a place, the order of things, who was there, what was said. \
Only where a source clearly bears on it. A different feeling or reading of the same events is \
not an inconsistency, and a story may compress or reorder on purpose: say so if it seems to.
- addition: a concrete detail in the sources the story doesn't have and could use: a name, a \
number, something said, a sensory detail, something that happened on those days that fits what \
the story is about. Specific, not generic; nothing the story already says.
- note: for each {{note}} the sources can answer, the answer. Skip notes they can't answer.

For each, story_quote is a short passage (a few words to a sentence) copied exactly from the \
story itself (the text under "## The story", never the plan's description above it), without the {{ }} markup and without markdown, that the suggestion is about. For a note, \
quote the note's own text. For an addition with no place in the story yet, quote the passage it \
would go after, or leave it empty. claim says what the sources show, in a sentence or two; \
suggestion says what the author might do, in a sentence. evidence lists the sources: ref is an \
event id or entry id exactly as given in brackets ([audio/...], [Note_...#2]), or route:YYYY-MM-DD \
or photos:YYYY-MM-DD for a day's summary; quote is the words of the source that show it (empty \
for a summary). Write in English.

Most important first. A dozen or two good suggestions beat many weak ones; give none of a kind \
if there are none. Don't repeat suggestions the author has already dismissed (listed at the end).
"""
CHECK_SHAPE = {
    "type": "object", "additionalProperties": False, "required": ["suggestions"],
    "properties": {"suggestions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "story_quote", "claim", "suggestion", "evidence"],
        "properties": {
            "kind": {"type": "string", "enum": ["inconsistency", "addition", "note"]},
            "story_quote": {"type": "string"}, "claim": {"type": "string"}, "suggestion": {"type": "string"},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["ref", "quote"],
                "properties": {"ref": {"type": "string"}, "quote": {"type": "string"}}}}}}}}}

def version(data):
    return '"' + hashlib.sha256(data).hexdigest()[:16] + '"'

# ---- inputs, read again only when their files change

_cache, _cache_lock = {}, threading.Lock()

def cached(paths, load):
    stamp = tuple(p.stat().st_mtime_ns if p.exists() else None for p in paths)
    key = (load.__name__, tuple(paths))
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    value = load()
    with _cache_lock:
        _cache[key] = (stamp, value)
    return value

def utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%MZ")

def latlon(r):
    """(lat, lon) of an index row, or () without them."""
    return (float(r["lat"]), float(r["lon"])) if r.get("lat") and r.get("lon") else ()

def day(text):
    """A plan's date: YY-MM-DD or YYYY-MM-DD; None if empty or not a date."""
    m = re.fullmatch(r"(\d{2}|\d{4})-(\d{1,2})-(\d{1,2})", text.strip())
    if not m:
        return None
    year = int(m[1]) + (2000 if len(m[1]) == 2 else 0)
    try:
        return date(year, int(m[2]), int(m[3]))
    except ValueError:
        return None

class LocalTimes:
    """Local times through the trip, from the rides' and photos' UTC offsets; at a place, where the
    photos give none nearby, from the time zone of the nearest town (Offsets.at)."""

    def __init__(self):
        self.offsets = local_offsets()

    def local(self, dt, lat=None, lon=None):
        place = towns() if lat is not None and lon is not None and self.offsets.far(dt) else None
        return dt + self.offsets.at(dt, place.zone(lat, lon) if place else None)

def offsets():
    return cached([INDEX / "photos.csv", BASE_DIR / "processing/track/offsets.csv"], lambda: LocalTimes())

def towns():
    return cached_towns()

def route_points():
    def load_route():
        return [(utc(r["utc"]), float(r["lat"]), float(r["lon"]), r["class"], r["source"])
                for r in rows(ROUTE_DIR / "route.csv")]
    return cached([ROUTE_DIR / "route.csv"], load_route)

def stays():
    def load_stays():
        try:
            from openlocationcode import openlocationcode as olc
        except ImportError:
            olc = None
        out = []
        for r in rows(STAYS):
            first, leaving = day(r.get("first_night") or ""), day(r.get("leaving") or "")
            if not first or not leaving:
                continue
            lat = lon = None
            code = (r.get("plus_code") or "").strip().upper()
            if olc and olc.isFull(code):
                area = olc.decode(code)
                lat, lon = round(area.latitudeCenter, 5), round(area.longitudeCenter, 5)
            out.append({"first_night": first.isoformat(), "leaving": leaving.isoformat(), "town": r.get("town", ""),
                        "notes": r.get("notes", ""), "lat": lat, "lon": lon})
        return out
    return cached([STAYS], load_stays)

def camera_times():
    """HH:MM of each photo's camera clock, which is local time, by file."""
    def load_camera():
        out = {}
        for r in rows(INDEX / "photos.csv"):
            m = re.match(r"\d{4}:\d{2}:\d{2} (\d{2}:\d{2})", r.get("taken") or "")
            if m:
                out[r["file"]] = m[1]
        return out
    return cached([INDEX / "photos.csv"], load_camera)

def exported():
    return cached([EXPORTED], lambda: {p.name for p in EXPORTED.iterdir()} if EXPORTED.is_dir() else set())

def ignored():
    return cached([IGNORED], lambda: {r["file"]: r.get("note", "") for r in rows(IGNORED)})

def index(name):
    path = EVENTS / "events.csv" if name == "events" else LOCATED / f"{name}.csv"
    return cached([path], lambda: rows(path))

# ---- stories

def stories():
    """Every story in the plans (the first row of a name wins), then any story file with no row."""
    out = {}
    for plan in sorted(PLANS.glob("*.csv")):
        for r in rows(plan):
            name = (r.get("Name") or "").strip()
            if not name or name in out:
                continue
            given = [(r.get(k) or "").strip() for k in ("Start time", "Stop time")]
            start, stop = (day(g) for g in given)
            problem = ""
            if any(g and not d for g, d in zip(given, (start, stop))):
                problem = f"the dates {given[0]!r} to {given[1]!r} aren't YY-MM-DD"
            elif bool(start) != bool(stop):
                problem = "only one of Start time and Stop time is filled in"
            elif start and stop < start:
                problem = "Stop time is before Start time"
            if problem:
                start = stop = None
            out[name] = {"name": name, "plan": plan.name, "description": r.get("Description") or "",
                         "size": r.get("Size") or "", "words": r.get("Words") or "",
                         "start": start.isoformat() if start else "", "stop": stop.isoformat() if stop else "",
                         "problem": problem, "has_file": (STORIES / f"{name}.md").is_file()}
    for p in sorted(STORIES.glob("*.md")):
        if p.stem not in out:
            out[p.stem] = {"name": p.stem, "plan": "", "description": "", "size": "", "words": "", "start": "",
                           "stop": "", "problem": "not in any story plan", "has_file": True}
    return out

def story(name):
    found = stories().get(name)
    if not found:
        raise Refused(404, f"no story {name!r} in story_plans/*.csv or raw/stories")
    return found

def story_file(name):
    """raw/stories/NAME.md, for a name from the plans: nothing else can be asked for."""
    path = STORIES / f"{story(name)['name']}.md"
    if path.parent != STORIES:
        raise Refused(403, "not a story")
    return path

# ---- a story's days

def entry_key(kind, file):
    return f"{kind}/{Path(file).stem}"

def gather(name, pad):
    """Everything the dashboard shows for the story's days."""
    meta = story(name)
    if not meta["start"]:
        raise Refused(400, f"{name}: {meta['problem'] or 'no Start time and Stop time in its plan'}")
    first = date.fromisoformat(meta["start"]) - timedelta(days=pad)
    last = date.fromisoformat(meta["stop"]) + timedelta(days=pad)
    inside = lambda d: bool(d) and first.isoformat() <= d <= last.isoformat()
    off, missing = offsets(), []
    # Wide enough for any time zone: points are kept by their own local day
    span = (datetime.combine(first, time()) - timedelta(hours=14), datetime.combine(last + timedelta(days=1), time()) + timedelta(hours=14))

    # The route in the span, recorded points thinned. A point's class is how it was reached, so a
    # step has the class of the point it ends at; its km count on the day it starts
    route, points = [], route_points()
    if not points:
        missing.append("processing/route/route.csv (make route)")
    times = [p[0] for p in points]
    a, b = bisect.bisect_left(times, span[0]), bisect.bisect_left(times, span[1])
    kept, last_kept, before = [], None, None
    for p in points[a:b]:
        local = off.local(p[0], p[1], p[2])
        if not inside(local.date().isoformat()):
            before = before if kept else p
            continue
        if not kept and before:  # where the first step comes from
            kept.append(before)
        if (last_kept and p[4] == "recorded" and p[3] == last_kept[3]
                and distance_km(last_kept[1], last_kept[2], p[1], p[2]) < SPACING_KM):
            continue
        kept.append(p)
        last_kept = p
    days = {}
    for d in range((last - first).days + 1):
        iso = (first + timedelta(days=d)).isoformat()
        days[iso] = {"date": iso, "km": {}, "first": None, "last": None, "legs": [], "stays": [],
                     "photos": 0, "photo_towns": {}, "photo_times": [], "events": 0, "entries": 0}
    for i, p in enumerate(kept):
        local = off.local(p[0], p[1], p[2])
        iso = local.date().isoformat()
        route.append([p[1], p[2], p[0].strftime("%Y-%m-%dT%H:%MZ"), p[3], p[4], iso, local.strftime("%H:%M")])
        if iso in days:
            d = days[iso]
            d["first"] = d["first"] or (p[1], p[2], local.strftime("%H:%M"))
            d["last"] = (p[1], p[2], local.strftime("%H:%M"))
            if i + 1 < len(kept) and kept[i + 1][3] != "stopped":
                q = kept[i + 1]
                d["km"][q[3]] = d["km"].get(q[3], 0) + distance_km(p[1], p[2], q[1], q[2])
    place = towns()
    if place is None:
        missing.append("processing/geonames/cities500.txt (make geonames)")
    for d in days.values():
        d["km"] = {k: round(v, 1) for k, v in d["km"].items() if v >= 0.1}
        for end in ("first", "last"):
            if d[end]:
                lat, lon, hhmm = d[end]
                town = place.nearest(lat, lon) if place else None
                d[end] = {"lat": lat, "lon": lon, "time": hhmm,
                          "town": f"{town[0]} ({town[1]})" if town else ""}

    legs = []
    for r in rows(ROUTE_DIR / "legs.csv"):
        start, end = utc(r["start_utc"]), utc(r["end_utc"])
        if start < span[1] and end > span[0]:
            leg = {k: r[k] for k in ("start_utc", "end_utc", "hours", "from", "to", "routed_km", "class", "mode",
                                     "mode_note", "flags")}
            leg["notes"] = "; ".join(x for x in (r["mode_note"], r["flags"]) if x)
            at = next((p for p in kept if p[0] >= start), None)
            leg["local_start"] = off.local(start, *(at[1:3] if at else ())).strftime("%Y-%m-%d %H:%M")
            legs.append(leg)
            iso = leg["local_start"][:10]
            if iso in days:
                days[iso]["legs"].append(len(legs) - 1)
    found_stays = [s for s in stays() if s["first_night"] <= last.isoformat() and s["leaving"] > first.isoformat()]
    if not STAYS.exists():
        missing.append("manual/stays.csv")
    for n, s in enumerate(found_stays):
        for iso, d in days.items():
            if s["first_night"] <= iso < s["leaving"]:
                d["stays"].append(n)

    photos, skipped, edited, camera = [], ignored(), exported(), camera_times()
    if not (LOCATED / "photos.csv").exists():
        missing.append("processing/located/photos.csv (make locate)")
    for r in index("photos"):
        if not inside(r["local_date"]):
            continue
        local = camera.get(r["file"]) or (
            off.local(utc(r["utc"]), *latlon(r)).strftime("%H:%M") if r["utc"] else "")
        name_ = Path(r["file"]).name
        photos.append({**{k: r[k] for k in ("file", "utc", "local_date", "lat", "lon", "town", "country",
                                            "position_source", "kind", "time_source")},
                       "local_time": local,
                       "show": f"{PHOTOS}/darktable_exported/{name_}" if name_ in edited else r["file"],
                       "edited": name_ in edited, "ignored": skipped.get(r["file"])})
        d = days[r["local_date"]]
        d["photos"] += 1
        if r["town"]:
            d["photo_towns"][r["town"]] = d["photo_towns"].get(r["town"], 0) + 1
        if local:
            d["photo_times"].append(local)
    photos.sort(key=lambda p: (p["local_date"], p["utc"], p["file"]))

    events = []
    for r in index("events"):
        when = r["date"] or r["entry_date"]
        if inside(when):
            events.append({**r, "day": when, "entry": entry_key(r["kind"], r["file"]),
                           "people": [x for x in r["people"].split(";") if x],
                           "tags": [x for x in r["tags"].split(";") if x]})
    events.sort(key=lambda e: (e["day"], e["entry_date"], e["utc"], e["event_id"]))
    with_events = {}
    for e in events:
        with_events[e["entry"]] = with_events.get(e["entry"], 0) + 1
        days[e["day"]]["events"] += 1

    entries = []
    for name_ in ("audio", "written", "blog"):
        for r in index(name_):
            kind = r.get("kind") or name_
            key = entry_key(kind, r["file"])
            if not (inside(r["local_date"]) or key in with_events):
                continue
            entries.append({"key": key, "kind": kind, "file": r["file"], "utc": r.get("utc", ""),
                            "local_date": r["local_date"], "town": r["town"], "country": r["country"],
                            "lat": r["lat"], "lon": r["lon"], "position_source": r["position_source"],
                            "words": int(r.get("words") or 0), "duration_min": r.get("duration_min", ""),
                            "local_time": off.local(utc(r["utc"]), *latlon(r)).strftime("%H:%M")
                            if r.get("utc") else "",
                            "events": with_events.get(key, 0), "later": not inside(r["local_date"])})
            if inside(r["local_date"]):
                days[r["local_date"]]["entries"] += 1
    entries.sort(key=lambda e: (e["local_date"], e["utc"], e["key"]))

    for d in days.values():
        times = sorted(d.pop("photo_times"))
        d["photo_span"] = [times[0], times[-1]] if times else []
    if not GPX_DIR.is_dir():
        missing.append("clean/gpx (make clean-data)")
    ride = rides(first, last, span, off, inside)
    ride["markers"] = ride_markers(ride, photos, entries, found_stays, events, place)
    return {"story": meta, "first": first.isoformat(), "last": last.isoformat(), "pad": pad,
            "days": list(days.values()), "route": route, "legs": legs, "stays": found_stays,
            "photos": photos, "events": events, "entries": entries, "ride": ride,
            "colours": settings.colours, "missing": missing}

# ---- the recorded rides of a story's days: Strava-like stats and an elevation profile

def gpx_points(path):
    """(utc, lat, lon, ele or None) of each timed point of a GPX file, read once."""
    def load_gpx():
        out = []
        for _, el in ET.iterparse(path):
            if el.tag == GPX_NS + "trkpt":
                t, e = el.find(GPX_NS + "time"), el.find(GPX_NS + "ele")
                if t is not None:
                    when = datetime.fromisoformat(t.text.replace("Z", "+00:00")).astimezone(timezone.utc)
                    out.append((when.replace(tzinfo=None), float(el.get("lat")), float(el.get("lon")),
                                float(e.text) if e is not None and e.text else None))
                el.clear()
        return out
    return cached([path], load_gpx)

def ride_files(first, last):
    """GPX files under clean/gpx that may hold points of these days. Komoot's are named by their
    day, which is enough to skip the rest; files without a day in the name are always read."""
    out = []
    for path in sorted(GPX_DIR.rglob("*.gpx")) if GPX_DIR.is_dir() else []:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        if m:
            d = date.fromisoformat(m[1])
            if not first - timedelta(days=1) <= d <= last + timedelta(days=1):
                continue
        out.append(path)
    return out

def climb(eles):
    """(gain, loss) in metres: every rise and drop, as Komoot counts its Elevation up and down.
    Its heights are already matched to the terrain, so smoothing them again only undercounts."""
    gain = sum(max(0, b - a) for a, b in zip(eles, eles[1:]))
    loss = sum(max(0, a - b) for a, b in zip(eles, eles[1:]))
    return gain, loss

def rides(first, last, span, off, inside):
    """The recorded rides of these days, joined end to end: the distance axis counts only what
    was ridden, so a lift or a gap between rides adds nothing. Where two files cover the same
    time, the one that starts first is kept."""
    tracks = []
    for path in ride_files(first, last):
        pts = [p for p in gpx_points(path) if span[0] <= p[0] < span[1]]
        if len(pts) > 1:
            # One local offset per file: rides don't run past midnight often enough to matter
            shift = off.local(pts[0][0], pts[0][1], pts[0][2]) - pts[0][0]
            pts = [p for p in pts if inside((p[0] + shift).date().isoformat())]
            if len(pts) > 1:
                tracks.append((pts, shift, path))
    tracks.sort(key=lambda t: t[0][0][0])
    points, until = [], None  # (utc, lat, lon, ele, local, ride number, km)
    for n, (pts, shift, _) in enumerate(tracks):
        for p in pts:
            if until and p[0] <= until:
                continue
            points.append((*p, p[0] + shift, n))
            until = p[0]
    if not points:
        return {"samples": [], "days": [], "total": None, "rides": 0}
    eles = [p[3] for p in points]
    have_ele = [e for e in eles if e is not None]
    if have_ele:  # fill a missing height from the one before it, or the first there is
        prev = have_ele[0]
        eles = [prev := (e if e is not None else prev) for e in eles]
    ele = eles if have_ele else [None] * len(points)

    km, step_km, moving, fast = [0.0], [0.0], [False], [0.0]
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        dt = (b[0] - a[0]).total_seconds()
        d = distance_km(a[1], a[2], b[1], b[2])
        joined = a[5] == b[5] and dt <= RIDE_GAP_S
        d = d if joined else 0.0
        km.append(km[-1] + d)
        step_km.append(d)
        moving.append(joined and dt > 0 and d / dt * 3600 >= RIDE_MOVING_KMH)
    # Max speed over a window of RIDE_SPEED_WINDOW_S, so one jumpy fix doesn't set it
    j = 0
    for i in range(1, len(points)):
        while (points[i][0] - points[j][0]).total_seconds() > RIDE_SPEED_WINDOW_S:
            j += 1
        dt = (points[i][0] - points[j][0]).total_seconds()
        same = points[i][5] == points[j][5]
        fast.append((km[i] - km[j]) / dt * 3600 if same and dt >= RIDE_SPEED_WINDOW_S / 2 else 0.0)

    def stats(ix):
        """Strava's numbers for the points at these indexes."""
        dist = sum(step_km[i] for i in ix if i)
        mov = sum((points[i][0] - points[i - 1][0]).total_seconds() for i in ix if i and moving[i])
        days_ = {}
        for i in ix:
            days_.setdefault(points[i][4].date(), []).append(i)
        elapsed = sum((points[v[-1]][0] - points[v[0]][0]).total_seconds() for v in days_.values())
        hs = [ele[i] for i in ix if ele[i] is not None]
        gain, loss = (0.0, 0.0)
        for v in days_.values():  # climbing counted ride by ride, not across the gaps between
            by_ride = {}
            for i in v:
                by_ride.setdefault(points[i][5], []).append(ele[i])
            for part in by_ride.values():
                if part and part[0] is not None:
                    g, l = climb(part)
                    gain, loss = gain + g, loss + l
        top = max((f for i, f in zip(ix, (fast[i] for i in ix)) if f <= RIDE_MAX_KMH), default=0.0)
        return {"km": round(dist, 1), "moving_s": round(mov), "elapsed_s": round(elapsed),
                "avg_kmh": round(dist / mov * 3600, 1) if mov else None, "max_kmh": round(top, 1),
                "gain_m": round(gain) if hs else None, "loss_m": round(loss) if hs else None,
                "max_ele": round(max(hs)) if hs else None, "min_ele": round(min(hs)) if hs else None,
                "rides": len({points[i][5] for i in ix})}

    by_day = {}
    for i, p in enumerate(points):
        by_day.setdefault(p[4].date().isoformat(), []).append(i)
    days = [{"date": d, "start_km": round(km[ix[0]], 2), "end_km": round(km[ix[-1]], 2), **stats(ix)}
            for d, ix in sorted(by_day.items())]
    total = stats(range(len(points)))

    # Thinned for the chart: a sample every so often along the way, and at every gap between rides
    every = max(RIDE_SAMPLE_KM, km[-1] / RIDE_MAX_SAMPLES)
    samples, at = [], None
    for i, p in enumerate(points):
        new_ride = i and points[i - 1][5] != p[5]
        if at is not None and km[i] - at < every and not new_ride and i != len(points) - 1:
            continue
        # Speed since the sample before, moving time only
        if samples:
            k = samples[-1][-1]
            mov = sum((points[x][0] - points[x - 1][0]).total_seconds() for x in range(k + 1, i + 1) if moving[x])
            speed = round((km[i] - km[k]) / mov * 3600, 1) if mov and not new_ride else None
        else:
            speed = None
        samples.append([round(km[i], 3), round(ele[i], 1) if ele[i] is not None else None,
                        p[0].strftime("%Y-%m-%dT%H:%M:%SZ"), round(p[1], 6), round(p[2], 6),
                        p[4].date().isoformat(), p[4].strftime("%H:%M"), speed, p[5], i])
        at = km[i]
    for s in samples:
        s.pop()  # the point's index, needed only above
    return {"samples": samples, "days": days, "total": total, "rides": len(tracks),
            "files": [str(t[2].relative_to(BASE_DIR)) for t in tracks]}

def plain(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold().strip()

def ride_markers(ride, photos, entries, stays_, events, place):
    """Where on the profile each map marker and each event goes, as {type, ref, km, how}:
    how is "time" (when it was, during a ride), "position" (closest the ride came to where it
    was, on its day), or for events "place" (the town it names, near that day's ride) or "entry"
    (where its entry was made). Anything the rides didn't come near is left off."""
    S = ride["samples"]
    if not S:
        return []
    times = [datetime.strptime(s[2], "%Y-%m-%dT%H:%M:%SZ") for s in S]

    def by_time(when):
        i = bisect.bisect_left(times, when)
        if 0 < i < len(S) and S[i - 1][8] == S[i][8]:
            a, b = times[i - 1], times[i]
            if (b - a).total_seconds() <= RIDE_GAP_S:
                f = (when - a) / (b - a) if b > a else 0
                return i - 1 if f < .5 else i, S[i - 1][0] + f * (S[i][0] - S[i - 1][0])
        return None

    def by_position(lat, lon, day=None, within=RIDE_NEAR_KM):
        best = None
        for i, s in enumerate(S):
            if day and s[5] != day:
                continue
            d = distance_km(lat, lon, s[3], s[4])
            if d <= within and (best is None or d < best[0]):
                best = (d, i)
        return (best[1], S[best[1]][0]) if best else None

    out = []

    def add(type_, ref, found, how):
        if found:
            out.append({"type": type_, "ref": ref, "km": round(found[1], 3), "how": how})

    for n, p in enumerate(photos):
        hit = by_time(utc(p["utc"])) if p["utc"] else None
        # A photo's own GPS beats its clock, which can be off
        if hit and p["lat"] and p["position_source"] == "photo_gps" and \
                distance_km(float(p["lat"]), float(p["lon"]), S[hit[0]][3], S[hit[0]][4]) > RIDE_NEAR_KM:
            hit = None
        if hit:
            add("photo", n, hit, "time")
        elif p["lat"]:
            add("photo", n, by_position(float(p["lat"]), float(p["lon"]), p["local_date"]), "position")
    for e in entries:
        if e["later"]:
            continue
        hit = by_time(utc(e["utc"])) if e["utc"] else None
        if hit and e["lat"] and distance_km(float(e["lat"]), float(e["lon"]), S[hit[0]][3], S[hit[0]][4]) > RIDE_NEAR_KM:
            hit = None
        if hit:
            add("entry", e["key"], hit, "time")
        elif e["lat"]:
            add("entry", e["key"], by_position(float(e["lat"]), float(e["lon"]), e["local_date"]), "position")
    for n, s in enumerate(stays_):
        if s.get("lat") is None:
            continue
        # Arriving on the first night, else leaving on the last day, else passing by
        add("stay", n, by_position(s["lat"], s["lon"], s["first_night"]) or
            by_position(s["lat"], s["lon"], s["leaving"]) or by_position(s["lat"], s["lon"]), "position")

    # Towns near each day's ride, by plain name, for the places events name
    near = {}
    if place:
        for d in {s[5] for s in S}:
            day_pts = [s for s in S if s[5] == d]
            pts = day_pts[::max(1, len(day_pts) // 100)]
            # A box round the day's ride, a little wider than RIDE_TOWN_KM, to skip most towns quickly
            pad = RIDE_TOWN_KM / 80
            box = (min(s[3] for s in pts) - pad, max(s[3] for s in pts) + pad,
                   min(s[4] for s in pts) - pad * 1.5, max(s[4] for s in pts) + pad * 1.5)
            for name, tlat, tlon, _, _ in place.nearby(pts[0][3], pts[0][4]):
                if not (box[0] <= tlat <= box[1] and box[2] <= tlon <= box[3]):
                    continue
                km_ = min(distance_km(tlat, tlon, s[3], s[4]) for s in pts)
                if km_ <= RIDE_TOWN_KM:
                    key = (d, plain(name))
                    if key not in near or km_ < near[key][0]:
                        near[key] = (km_, tlat, tlon)
    for e in events:
        hit, how = None, "place"
        for part in re.split(r",|\s+(?:to|and|→|->|-)\s+|\s+–\s+", e["place"] or ""):
            town = near.get((e["day"], plain(part)))
            if town:
                hit = by_position(town[1], town[2], e["day"], RIDE_TOWN_KM)
                break
        if not hit and e["lat"] and e["entry_date"] == e["day"]:
            hit, how = by_position(float(e["lat"]), float(e["lon"]), e["day"]), "entry"
        add("event", e["event_id"], hit, how)
    out.sort(key=lambda m: m["km"])
    return out

# ---- one entry

def index_row(kind, stem):
    for name in ("audio", "written", "blog"):
        for r in index(name):
            if (r.get("kind") or name) == kind and Path(r["file"]).stem == stem:
                return r
    raise Refused(404, f"no entry {kind}/{stem} in the index")

def entry(kind, stem):
    """The entry as the Diary view shows it. An entry too short for make events (or with no
    transcript) is read from its row: its text, if any, and audio."""
    from api import diary
    row = index_row(kind, stem)
    try:
        out = diary.entry_data(diary.find(kind, stem))
    except Refused:
        text_path = row.get("transcript") if kind == "audio" else row["file"]
        text = ""
        if text_path and (BASE_DIR / text_path).is_file():
            text = entry_text({"text": BASE_DIR / text_path})
        audio = COMPRESSED_DIR / f"{stem}.ogg"
        out = {"kind": kind, "kind_name": KINDS.get(kind, kind), "stem": stem, "info": row, "text_file": text_path or "",
               "audio": "/files/" + quote(str(audio.relative_to(BASE_DIR))) if kind == "audio" and audio.exists() else "",
               "segments": [[None, None, p.strip()] for p in re.split(r"\n+", text) if p.strip()], "timing": "",
               "events": [], "status": ""}
    return out

# ---- Claude's suggestions

_running, _running_lock = set(), threading.Lock()

def check_path(name):
    return CHECKS / f"{story(name)['name']}.json"

def load_check(name):
    path = check_path(name)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

def write_check(name, record):
    path = check_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(part, path)

def cut(texts, budget):
    """The texts, the longest cut short so they add up to no more than budget; and which were cut."""
    if sum(map(len, texts)) <= budget:
        return texts, set()
    low, high = 0, max(map(len, texts))
    while low < high:  # the largest cap that fits
        mid = (low + high + 1) // 2
        low, high = (mid, high) if sum(min(len(t), mid) for t in texts) <= budget else (low, mid - 1)
    return [t if len(t) <= low else t[:low] for t in texts], {i for i, t in enumerate(texts) if len(t) > low}

def prompt_text(name, data, text, dismissed):
    meta = data["story"]
    out = [f"# Story: {name}", f"Plan: {meta['description'].strip()}" if meta["description"].strip() else "",
           f"Its days: {meta['start']} to {meta['stop']}" + (f"; the sources below run {data['pad']} days either side, "
                                                             f"{data['first']} to {data['last']}" if data["pad"] else ""),
           "", "## The story", "", text.strip() or "(empty so far)", "", "## Day by day"]
    for d in data["days"]:
        bits = []
        if d["km"]:
            bits.append("route " + ", ".join(f"{k} {v} km" for k, v in sorted(d["km"].items(), key=lambda kv: -kv[1])))
        if d["first"] and d["last"]:
            bits.append(f"from {d['first']['town'] or 'unknown'} at {d['first']['time']} to "
                        f"{d['last']['town'] or 'unknown'} at {d['last']['time']} (local)")
        for n in d["legs"]:
            leg = data["legs"][n]
            bits.append(f"{leg['mode'] or leg['class']} {leg['local_start'][11:]} {leg['from']} to {leg['to']}, "
                        f"{leg['routed_km']} km{', ' + leg['notes'] if leg['notes'] else ''}")
        for n in d["stays"]:
            s = data["stays"][n]
            bits.append(f"night in {s['town']}" + (f" ({s['notes']})" if s["notes"] else ""))
        if d["photos"]:
            where = ", ".join(f"{t} {c}" for t, c in sorted(d["photo_towns"].items(), key=lambda kv: -kv[1]))
            bits.append(f"{d['photos']} photos" + (f" {d['photo_span'][0]} to {d['photo_span'][1]}" if d["photo_span"] else "")
                        + (f" in {where}" if where else ""))
        out.append(f"- [route:{d['date']}] {date.fromisoformat(d['date']):%a} {d['date']}: " + ("; ".join(bits) or "nothing recorded"))
    out += ["", "## Events"]
    for e in data["events"]:
        out.append(f"- [{e['event_id']}] {e['day']}{' (guessed)' if e['date_guessed'] == 'yes' else ''}"
                   f"{', ' + e['place'] if e['place'] else ''}"
                   f"{'; with ' + ', '.join(e['people']) if e['people'] else ''}"
                   f"{'; tags ' + ', '.join(e['tags']) if e['tags'] else ''}"
                   f" (from [{e['entry']}], made {e['entry_date']}): {e['title']}. {e['summary']}"
                   f"{' Quote: “' + e['quote'] + '”' if e['quote'] else ''}")
    if not data["events"]:
        out.append("(none indexed)")
    texts, heads = [], []
    for e in data["entries"]:
        row = index_row(e["kind"], Path(e["file"]).stem)
        path = row.get("transcript") if e["kind"] == "audio" else row["file"]
        body = entry_text({"text": BASE_DIR / path}).strip() if path and (BASE_DIR / path).is_file() else ""
        if not body:
            continue
        texts.append(body)
        heads.append(f"### [{e['key']}] {KINDS.get(e['kind'], e['kind'])}, made {e['local_date'] or 'on an unknown day'}"
                     f"{' ' + e['local_time'] if e['local_time'] else ''}"
                     f"{', ' + e['town'] + ' ' + e['country'] if e['town'] else ''}"
                     f"{' (recalls earlier days)' if e['later'] else ''}")
    texts, short = cut(texts, PROMPT_BUDGET)
    out += ["", "## Diary entries"]
    for n, (head, body) in enumerate(zip(heads, texts)):
        out += ["", head + (" [cut short: too long to send whole]" if n in short else ""), "", body]
    if not texts:
        out.append("(none)")
    if dismissed:
        out += ["", "## Dismissed by the author: don't suggest these again"]
        out += [f"- {s['kind']}: {s['claim']}" for s in dismissed]
    return "\n".join(out) + "\n"

def suggestion_id(s):
    return hashlib.sha1(f"{s['kind']}\0{s['story_quote']}\0{s['claim']}".encode()).hexdigest()[:12]

def run_check(name, body, pad):
    model = (parse(body).get("model") or "opus").strip()
    if model not in MODELS:
        raise Refused(400, f"model should be one of {', '.join(MODELS)}")
    with _running_lock:
        if name in _running:
            raise Refused(409, "Claude is already checking this story")
        _running.add(name)
    try:
        path = story_file(name)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        before = load_check(name) or {}
        dismissed = [s for s in before.get("suggestions", []) if s.get("dismissed")]
        data = gather(name, pad)
        asked = prompt_text(name, data, text, dismissed)
        started = datetime.now()
        try:
            answer = structured(CHECK_PROMPT, asked, CHECK_SHAPE, backend="cli", model=model)
        except (LimitReached, RetryableError, RuntimeError) as e:
            raise Refused(502, f"Claude didn't answer: {e}")
        found = []
        for s in answer["suggestions"]:
            # Claude often copies the brackets the prompt puts round ids: [audio/Recording 97]
            evidence = [{**e, "ref": e["ref"].strip().strip("[]").strip()} for e in s["evidence"]]
            s = {**s, "evidence": evidence, "story_quote": s["story_quote"].strip(), "dismissed": False}
            s["id"] = suggestion_id(s)
            found.append(s)
        ids = {s["id"] for s in found}
        record = {"story": name, "model": model, "at": started.isoformat(timespec="seconds"),
                  "seconds": round((datetime.now() - started).total_seconds()), "pad": pad,
                  "story_version": version(text.encode("utf-8")), "prompt_chars": len(asked),
                  "suggestions": found + [s for s in dismissed if s["id"] not in ids]}
        write_check(name, record)
        return record
    finally:
        with _running_lock:
            _running.discard(name)

def dismiss(name, body):
    data = parse(body)
    with _running_lock:
        record = load_check(name)
        if not record:
            raise Refused(404, "no suggestions for this story yet")
        for s in record["suggestions"]:
            if s["id"] == data.get("id"):
                s["dismissed"] = bool(data.get("dismissed", True))
                break
        else:
            raise Refused(404, "no such suggestion: run the check again?")
        write_check(name, record)
    return record

def parse(body):
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Refused(400, f"not JSON: {e}")
    if not isinstance(data, dict):
        raise Refused(400, "not a JSON object")
    return data

def handle(method, parts, query, body, headers):
    """The answer to a request under /api/story/: data, or (code, bytes, headers) for the story's text."""
    pad = (parse_qs(query).get("pad") or ["0"])[0]
    pad = max(0, min(MAX_PAD, int(pad))) if pad.isdigit() else 0
    if parts == ["list"] and method == "GET":
        return list(stories().values())
    if len(parts) == 3 and parts[0] == "entry" and method == "GET":
        return entry(parts[1], parts[2])
    if len(parts) == 1 and method == "GET":
        return gather(parts[0], pad)
    if len(parts) == 2 and parts[1] == "text" and method == "GET":
        file = story_file(parts[0])
        if not file.is_file():
            raise Refused(404, f"no raw/stories/{file.name} yet")
        data = file.read_bytes()
        tag = version(data)
        if headers.get("If-None-Match") == tag:
            return 304, b"", {"ETag": tag}
        return 200, data, {"Content-Type": "text/markdown; charset=utf-8", "ETag": tag}
    if len(parts) == 2 and parts[1] == "check":
        story(parts[0])
        if method == "GET":
            return load_check(parts[0])
        if method == "POST":
            return run_check(parts[0], body, pad)
    if len(parts) == 3 and parts[1:] == ["check", "dismiss"] and method == "POST":
        return dismiss(parts[0], body)
    return None
