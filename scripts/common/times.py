"""Times: the formats the files use, and UTC offsets through the trip.

Files write UTC times to the minute as YYYY-MM-DDTHH:MMZ (stamp, parse). EXIF times are
YYYY:MM:DD HH:MM:SS, the camera's local time or GPS's UTC (exif_time).
"""
import bisect
from datetime import datetime, timedelta, timezone

from common.tables import read_rows
from settings import settings

STAMP = "%Y-%m-%dT%H:%MZ"


def stamp(t):
    return t.strftime(STAMP)


def parse(text):
    """An aware UTC datetime from YYYY-MM-DDTHH:MMZ."""
    return datetime.strptime(text, STAMP).replace(tzinfo=timezone.utc)


def exif_time(value):
    """A naive datetime from an EXIF time, or None."""
    return datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S") if value else None


def as_utc(dt):
    """Naive datetimes are taken as UTC; local time was within an hour or two of it."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class Offsets:
    """UTC offsets through the trip: (utc, offset) pairs, from the rides' GPX times and from
    photos with both camera and GPS times."""

    def __init__(self, offsets):
        quarter = timedelta(minutes=15)
        self.points = sorted((utc, round(offset / quarter) * quarter) for utc, offset in offsets)
        self.times = [p[0].replace(tzinfo=None) for p in self.points]

    def at(self, dt, zone=None):
        """The offset of the sample nearest in time; dt may be UTC or local.

        Given the place's time zone (Towns.zone), it's used instead where that sample is more than
        lookup.sample_days away: the first samples are from Germany, so without it Brisbane and
        Taipei, before them, come out at Germany's offset. dt is taken as the zone's wall time,
        which is an hour out at most, in the hour summer time starts or ends. Without samples:
        the zone's, or zero."""
        dt = dt.replace(tzinfo=None)
        if zone and self.far(dt):
            return zone.utcoffset(dt)
        return self.points[self.nearest(dt)][1] if self.points else timedelta()

    def nearest(self, dt):
        i = bisect.bisect_left(self.times, dt)
        return min((k for k in (i - 1, i) if 0 <= k < len(self.times)), key=lambda k: abs(self.times[k] - dt))

    def far(self, dt):
        """Whether the nearest sample is more than lookup.sample_days from dt: a place's time zone is
        worth looking up (Towns.zone, which is slow) only then."""
        dt = dt.replace(tzinfo=None)
        return not self.points or abs(self.times[self.nearest(dt)] - dt) > timedelta(days=settings.lookup.sample_days)

    def local(self, utc, zone=None):
        """Naive local time of an aware UTC time."""
        return (utc + self.at(utc, zone)).replace(tzinfo=None)

    def utc(self, local, zone=None):
        """Aware UTC time of a naive local time."""
        return (local - self.at(local, zone)).replace(tzinfo=timezone.utc)


def track_offsets():
    """(utc, offset) per ride, from make track's offsets.csv."""
    from repo import TRACK_OFFSETS
    return [(parse(r["utc"]), timedelta(minutes=int(r["offset_min"]))) for r in read_rows(TRACK_OFFSETS)]


def photo_offsets(photos):
    """(utc, camera minus GPS time) of each indexed photo (processing/index/photos.csv rows) with both."""
    pairs = []
    for r in photos:
        if r.get("taken") and r.get("gps_time"):
            utc = exif_time(r["gps_time"])
            pairs.append((utc.replace(tzinfo=timezone.utc), exif_time(r["taken"]) - utc))
    return pairs


def local_offsets():
    """Offsets from the rides (make track) and from the photos with both a camera and a GPS time."""
    from repo import INDEX
    return Offsets(track_offsets() + photo_offsets(read_rows(INDEX / "photos.csv")))


def place_time(day, time, offsets, zone=None):
    """UTC of a known place's time on day: HH:MM[:SS] local time, made UTC with offsets (in the
    place's time zone, if given: see Offsets.at), or already UTC if it ends in Z (as the review
    app writes them)."""
    if time.endswith("Z"):
        return datetime.fromisoformat(f"{day}T{time[:-1]}").replace(tzinfo=timezone.utc)
    local = datetime.fromisoformat(f"{day}T{time}")
    return (local - offsets.at(local, zone)).replace(tzinfo=timezone.utc)
