"""Recorded rides, one <trk> per ride: a recording left running through a night is split.

Where a pause of gpx_pause_hours or more crosses local midnight (a ride not ended the evening
before), the points after it are a ride of their own: a further <trk>, a copy of the raw one
with the other rides' points taken out, so its metadata and every point's data stay. Long
stops within a day (lunch, a puncture) are left alone: they are still one ride. Times are local
by each point's own UTC offset (Strava's are UTC, close enough). A file with nothing to split
is copied as it is.
"""
import copy
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from settings import settings

PATTERNS = ["gpx/*.gpx"]
NS = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", NS)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")


def point_time(trkpt):
    t = trkpt.find(f"{{{NS}}}time")
    return datetime.fromisoformat(t.text) if t is not None else None


def split_points(times):
    """Indexes of the points that start a new ride: after an overnight pause."""
    starts, prev = [], None
    for i, t in enumerate(times):
        if t is None:
            continue
        if prev and t - prev >= timedelta(hours=settings.gpx_pause_hours) and t.date() != prev.date():
            starts.append(i)
        prev = t
    return starts


def keep_only(root, keep):
    """Take every point whose document-order index isn't in keep out of root's tracks, and the
    segments and tracks left empty."""
    index = 0
    for seg in list(root.iter(f"{{{NS}}}trkseg")):
        for trkpt in list(seg.findall(f"{{{NS}}}trkpt")):
            if index not in keep:
                seg.remove(trkpt)
            index += 1
    for trk in list(root.findall(f"{{{NS}}}trk")):
        for seg in list(trk.findall(f"{{{NS}}}trkseg")):
            if not seg.findall(f"{{{NS}}}trkpt"):
                trk.remove(seg)
        if not trk.findall(f"{{{NS}}}trkseg"):
            root.remove(trk)


def clean(src, dst):
    tree = ET.parse(src)
    root = tree.getroot()
    times = [point_time(p) for p in root.iter(f"{{{NS}}}trkpt")]
    starts = split_points(times)
    if not starts:
        shutil.copyfile(src, dst)
        return
    bounds = [0, *starts, len(times)]
    rides = []
    for a, b in zip(bounds, bounds[1:]):
        part = copy.deepcopy(root)
        keep_only(part, set(range(a, b)))
        rides += part.findall(f"{{{NS}}}trk")
    for trk in root.findall(f"{{{NS}}}trk"):
        root.remove(trk)
    root.extend(rides)
    tree.write(dst, encoding="UTF-8", xml_declaration=True)
