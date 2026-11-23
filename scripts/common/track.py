"""The track, as positions in time, and the rides it came from."""
import bisect
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from common.tables import read_rows
from common.times import as_utc, parse
from settings import settings

GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def ride_points(path):
    """[[(utc, lat, lon, UTC offset), ...] per ride] of a cleaned GPX file: each <trk> is a ride
    (the cleaner splits a recording left running overnight into several)."""
    rides, current = [], None
    for event, el in ET.iterparse(path, events=("start", "end")):
        if event == "start" and el.tag == GPX_NS + "trk":
            current = []
        elif event == "end" and el.tag == GPX_NS + "trkpt":
            t = el.find(GPX_NS + "time")
            if t is not None and current is not None:
                local = datetime.fromisoformat(t.text)
                current.append((local.astimezone(timezone.utc), float(el.get("lat")), float(el.get("lon")),
                                local.utcoffset()))
            el.clear()
        elif event == "end" and el.tag == GPX_NS + "trk":
            rides.append(current)
            current = None
    return rides


def gives_offsets(path):
    """Whether a GPX file's times carry the phone's own UTC offset: Strava's are always UTC."""
    with open(path, encoding="utf-8") as f:
        return 'creator="StravaGPX"' not in f.read(500)


class Track:
    """Time-sorted (utc, lat, lon, source) points; source says where each came from."""

    def __init__(self, points_csv=None):
        """Points from a csv with utc and lat, lon (make track's points.csv); or none, for add to fill."""
        self.points, self.times = [], []
        if points_csv:
            self.add((parse(r["utc"]), float(r["lat"]), float(r["lon"]), "track") for r in read_rows(points_csv))

    def add(self, points):
        """More (utc, lat, lon, source) points, such as photo GPS."""
        self.points = sorted([*self.points, *points], key=lambda p: p[0])
        self.times = [p[0] for p in self.points]

    def position(self, dt):
        """(lat, lon, hours to the nearest point, its source), or None beyond lookup.max_hours.

        A time between two points takes the nearer one: on rest days that's where the last ride
        ended or the next one starts."""
        if not self.points:
            return None
        dt = as_utc(dt)
        i = bisect.bisect_left(self.times, dt)
        nearest = min((j for j in (i - 1, i) if 0 <= j < len(self.times)),
                      key=lambda j: abs(self.times[j] - dt))
        utc, lat, lon, source = self.points[nearest]
        hours = abs(utc - dt).total_seconds() / 3600
        return (lat, lon, hours, source) if hours <= settings.lookup.max_hours else None
