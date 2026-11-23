"""The Stays view's data: your stays beside the ones make stays found, and what each night says.

  GET /api/stays                every stay in manual/stays.csv, each with the found stay that shares the
                                most of its nights, and every found stay that shares none. Status:
                                  confirmed  you've confirmed it (its checked column)
                                  matches    the found stay has the same dates and place
                                  differs    the found stay has other dates, or a place further away
                                             than stays.radius_km: worth a look
                                  yours      nothing found over its nights to compare with
                                  new        found, but not in your stays: add it, or say it's not one
                                  dismissed  found, and you said it's not a stay
  GET /api/stays/days?first=YYYY-MM-DD&last=YYYY-MM-DD
                                the track, the photos with GPS and every night's candidate places over
                                those local days (and a day either side), for the map
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

from openlocationcode import openlocationcode as olc

from common.geo import distance_km
from common.photos import gps_photos
from common.tables import read_json, read_rows
from common.times import parse
from repo import FOUND_STAYS, INDEX, TRACK_POINTS
from settings import settings
from shared import cached, offsets, towns
from store import rows

RADIUS = settings.stays.radius_km


def place(code):
    if code and olc.isFull(code):
        area = olc.decode(code)
        return round(area.latitudeCenter, 6), round(area.longitudeCenter, 6)
    return None


def nights(first, leaving):
    a, b = date.fromisoformat(first), date.fromisoformat(leaving)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days)]


def compare(row, found):
    """How a stay of yours differs from the found one: the days its ends are out by, and the km."""
    mine = place(row["plus_code"])
    out = {"first_night_days": (date.fromisoformat(row["first_night"]) - date.fromisoformat(found["first_night"])).days,
           "leaving_days": (date.fromisoformat(row["leaving"]) - date.fromisoformat(found["leaving"])).days,
           "km": round(distance_km(*mine, found["lat"], found["lon"]), 2) if mine else None}
    out["same"] = out["first_night_days"] == 0 and out["leaving_days"] == 0 and out["km"] is not None and out["km"] <= RADIUS
    return out


def stays():
    data = read_json(FOUND_STAYS, {"stays": [], "nights": {}})
    found = data["stays"]
    dismissed = [r for r in rows("dismissed") if r["check"] == "found_stay"]
    items, taken = [], set()
    for row in rows("stays"):
        try:
            mine = set(nights(row["first_night"], row["leaving"]))
        except ValueError:
            mine = set()
        best = max(found, key=lambda s: len(mine & set(s["night_dates"])), default=None)
        match = best if best and mine & set(best["night_dates"]) else None
        taken.update(s["key"] for s in found if mine & set(s["night_dates"]))
        diff = compare(row, match) if match else None
        status = ("confirmed" if row["checked"] else "yours" if not match else "matches" if diff["same"] else "differs")
        at = place(row["plus_code"])
        items.append({"key": f"stay:{row['id']}", "kind": "stay", "row": row, "found": match, "diff": diff,
                      "status": status, "lat": at[0] if at else None, "lon": at[1] if at else None,
                      "first_night": row["first_night"], "leaving": row["leaving"],
                      "nights": len(mine), "town": row["town"]})
    for s in found:
        if s["key"] in taken:
            continue
        gone = next((d for d in dismissed if d["start_utc"] == s["first_night"]
                     and distance_km(float(d["lat"]), float(d["lon"]), s["lat"], s["lon"]) <= RADIUS), None)
        items.append({"key": f"found:{s['key']}", "kind": "found", "row": None, "found": s, "diff": None,
                      "status": "dismissed" if gone else "new", "dismissed": gone["id"] if gone else None,
                      "lat": s["lat"], "lon": s["lon"], "first_night": s["first_night"], "leaving": s["leaving"],
                      "nights": s["nights"], "town": s["town"]})
    items.sort(key=lambda i: (i["first_night"], i["key"]))
    return {"radius_km": RADIUS, "items": items, "found_built": FOUND_STAYS.stat().st_mtime if FOUND_STAYS.exists() else None}


def track_points():
    def load():
        kept, last = [], None
        for r in read_rows(TRACK_POINTS):
            t = parse(r["utc"])
            lat, lon = float(r["lat"]), float(r["lon"])
            if last and distance_km(last[0], last[1], lat, lon) < 0.03 and (t - last[2]).total_seconds() < 1800:
                continue
            last = (lat, lon, t)
            kept.append((t, round(lat, 5), round(lon, 5)))
        return kept
    return cached([TRACK_POINTS], load)


def photo_points():
    def load():
        files = {}
        for r in read_rows(INDEX / "photos.csv"):
            if r["gps_time"] and r["lat"]:
                files[(r["gps_time"][:16], round(float(r["lat"]), 6), round(float(r["lon"]), 6))] = r["file"]
        out = []
        for utc, lat, lon in gps_photos(towns()):
            out.append((utc, lat, lon, files.get((utc.strftime("%Y:%m:%d %H:%M"), round(lat, 6), round(lon, 6)), "")))
        return out
    return cached([INDEX / "photos.csv"], load)


def days(query):
    """The track, photos and nights over local days first..last, and a day either side. Local days are
    taken by the nearest UTC offset, without asking a town's time zone: close enough for a map."""
    q = parse_qs(query)
    first = date.fromisoformat(q["first"][0]) - timedelta(days=1)
    last = date.fromisoformat(q["last"][0]) + timedelta(days=2)
    lo = datetime.combine(first, datetime.min.time(), timezone.utc) - timedelta(hours=14)
    hi = datetime.combine(last, datetime.min.time(), timezone.utc) + timedelta(hours=14)
    off = offsets()

    def local_text(t):
        return (t + off.at(t)).strftime("%Y-%m-%dT%H:%M")

    track = [[lat, lon, t.strftime("%Y-%m-%dT%H:%MZ"), local_text(t)] for t, lat, lon in track_points() if lo <= t < hi]
    photos = [{"lat": lat, "lon": lon, "utc": t.strftime("%Y-%m-%dT%H:%MZ"), "local": local_text(t), "file": f,
               "name": Path(f).name} for t, lat, lon, f in photo_points() if lo <= t < hi]
    data = read_json(FOUND_STAYS, {"nights": {}})
    night = {d: c for d, c in data["nights"].items() if first.isoformat() <= d <= last.isoformat()}
    return {"track": track, "photos": photos, "nights": night}


def handle(method, parts, query, body):
    if method == "GET" and parts == []:
        return stays()
    if method == "GET" and parts == ["days"]:
        return days(query)
    return None

