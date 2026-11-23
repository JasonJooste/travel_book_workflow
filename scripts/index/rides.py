"""Each recorded ride: where and when it started and ended, its length, and the phone's UTC offset.

One row per GPX file; a file the cleaner split holds several rides, so the columns are JSON lists
of [start_utc, start_lat, start_lon, end_utc, end_lat, end_lon, km, offset_min] per ride (offset_min
empty for Strava, whose times are all UTC), plus how many points they have.
"""
import json

from common.geo import distance_km
from common.times import stamp
from common.track import gives_offsets, ride_points

PATTERNS = ["gpx/*.gpx"]
COLUMNS = ["rides", "points", "source"]


def row(path):
    rides, offsets, count = [], gives_offsets(path), 0
    for points in ride_points(path):
        count += len(points)
        if not points:
            continue
        a, b = points[0], points[-1]
        km = sum(distance_km(p[1], p[2], q[1], q[2]) for p, q in zip(points, points[1:]))
        offset = round(a[3].total_seconds() / 60) if offsets and a[3] is not None else ""
        rides.append([stamp(a[0]), round(a[1], 6), round(a[2], 6), stamp(b[0]), round(b[1], 6), round(b[2], 6),
                      round(km, 2), offset])
    return {"rides": json.dumps(rides), "points": count, "source": path.parent.name}
