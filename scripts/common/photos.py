"""When each photo was taken, in UTC and local time, from its EXIF (make index's photos.csv).

The UTC time is, best first: GPS's (time_source gps); a video's CreateDate, which QuickTime stores
in UTC (video); the camera's time less the offset it wrote (camera_offset); or the camera's time
less the UTC offset nearest in time (camera_nearby_offset). Once the photo's place is known, the
time zone there may say the time was another, where the offset samples are days away (Brisbane,
Taipei): see Offsets.at.
"""
from datetime import datetime, timezone

from common.tables import read_rows
from common.times import Offsets, exif_time, track_offsets
from repo import INDEX
from settings import settings


def read():
    """The photo index's rows."""
    return read_rows(INDEX / "photos.csv")


def parsed(r):
    """(camera time, utc, time source, lat, lon) of an index row."""
    camera = exif_time(r["taken"])
    if gps := exif_time(r["gps_time"]):
        utc, source = gps.replace(tzinfo=timezone.utc), "gps"
    elif r["kind"] == "video" and r["created"]:
        utc, source = exif_time(r["created"]).replace(tzinfo=timezone.utc), "video"
    elif camera and r["offset"]:
        utc = datetime.fromisoformat(camera.isoformat() + r["offset"]).astimezone(timezone.utc)
        source = "camera_offset"
    else:
        utc, source = None, "camera"  # local only; the offset comes from nearby photos
    lat = float(r["lat"]) if r["lat"] else None
    lon = float(r["lon"]) if r["lon"] else None
    return camera, utc, source, lat, lon


def index_offsets(rows):
    """UTC offsets from the rides and from every photo with a camera time and a UTC one."""
    pairs = []
    for r in rows:
        camera, utc, source, _, _ = parsed(r)
        if camera and source in ("gps", "camera_offset"):
            pairs.append((utc, camera - utc.replace(tzinfo=None)))
    return Offsets(track_offsets() + pairs)


def timed(rows, offsets, place, zone):
    """[{file, kind, utc, local_date, time_source, lat, lon, place}] of the photos taken on the trip's
    local days. place(utc, local_date, lat, lon) gives where a photo was (its own GPS, or a guess), and
    zone(place) the time zone there, or None: it's only asked where the offsets are far."""
    out = []
    for r in rows:
        camera, utc, source, lat, lon = parsed(r)
        if not (camera or utc):
            continue
        if utc is None:
            utc, source = offsets.utc(camera), "camera_nearby_offset"
        local = camera or offsets.local(utc)
        if not settings.trip.start <= local.date() <= settings.trip.end:
            continue
        where = place(utc, local.date(), lat, lon)
        z = zone(where) if offsets.far(camera or utc) else None
        if z and source == "camera_nearby_offset":
            better = offsets.utc(camera, z)
            if better != utc:
                utc, where = better, place(better, local.date(), lat, lon)
        elif z and not camera:
            better = offsets.local(utc, z)
            if better.date() != local.date():
                local = better
                if not settings.trip.start <= local.date() <= settings.trip.end:
                    continue
                where = place(utc, local.date(), lat, lon)
        out.append({"file": r["file"], "kind": r["kind"], "utc": utc, "local_date": local.date(),
                    "time_source": source, "lat": lat, "lon": lon, "place": where})
    return sorted(out, key=lambda p: p["utc"])


def gps_photos(towns):
    """(utc, lat, lon) of each photo with its own GPS position, timed as make locate times them (to the
    minute, as its CSVs have it)."""
    rows = read()
    own = [r for r in rows if r["lat"] and r["lon"]]
    found = timed(own, index_offsets(rows), lambda utc, day, lat, lon: (lat, lon),
                  lambda where: towns.zone(*where))
    return [(p["utc"].replace(second=0, microsecond=0), p["lat"], p["lon"]) for p in found]

