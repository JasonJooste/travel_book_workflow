"""What the review app's API modules share: inputs read again only when their files change, and
local times through the trip."""
import threading
from datetime import datetime, timezone

from common.times import local_offsets
from common.towns import Towns
from repo import CITIES, INDEX, TRACK_OFFSETS

_cache, _lock = {}, threading.Lock()


def cached(paths, load):
    """load(), remembered until one of paths changes."""
    stamp = tuple(p.stat().st_mtime_ns if p.exists() else None for p in paths)
    key = (load.__qualname__, tuple(map(str, paths)))
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    value = load()
    with _lock:
        _cache[key] = (stamp, value)
    return value


def towns():
    return cached([CITIES], lambda: Towns() if CITIES.exists() else None)


def offsets():
    return cached([TRACK_OFFSETS, INDEX / "photos.csv"], local_offsets)


def local(utc, lat=None, lon=None):
    """(naive local datetime, UTC offset in minutes) of an aware UTC time; the place, if given, is
    asked for its time zone where the offset samples are far (Brisbane, Taipei)."""
    off = offsets()
    zone = None
    if lat is not None and lon is not None and off.far(utc):
        place = towns()
        zone = place.zone(lat, lon) if place else None
    delta = off.at(utc, zone)
    return (utc + delta).replace(tzinfo=None), round(delta.total_seconds() / 60)


def when(utc, lat=None, lon=None):
    """A UTC time as the app shows it: {"utc": "...Z", "local": "YYYY-MM-DDTHH:MM", "offset": minutes}."""
    if isinstance(utc, str):
        utc = datetime.strptime(utc, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    t, offset = local(utc, lat, lon)
    return {"utc": utc.strftime("%Y-%m-%dT%H:%MZ"), "local": t.strftime("%Y-%m-%dT%H:%M"), "offset": offset}


def offset_table():
    """[[minutes since 1970 UTC, offset in minutes]] of every offset sample, for the app to turn the
    times it picks on the map into local time."""
    off = offsets()
    return [[int(t.timestamp() // 60), round(o.total_seconds() / 60)] for t, o in off.points]
