"""When and where each photo and video was taken, as its EXIF says, from one exiftool call.

taken is the camera's local time (DateTimeOriginal) and offset its UTC offset where the camera
wrote one; created is a video's CreateDate (QuickTime stores UTC); gps_time is GPS's UTC. lat/lon
are signed decimals. make locate turns these into a UTC time, a local date and a place.
"""
import csv
import io
import subprocess
from pathlib import Path

PATTERNS = ["photos/*.jpg", "photos/*.jpeg", "photos/*.png", "photos/*.heic", "photos/*.mp4", "photos/*.mov",
            "photos/*.3gp"]
COLUMNS = ["kind", "taken", "offset", "created", "gps_time", "lat", "lon"]
VIDEO = {".mp4", ".mov", ".3gp"}
TAGS = {"taken": "DateTimeOriginal", "offset": "OffsetTimeOriginal", "created": "CreateDate",
        "gps_time": "GPSDateTime", "lat": "GPSLatitude", "lon": "GPSLongitude"}


def rows(paths):
    # File names on stdin (-@ -), as thousands of them would overflow the command line
    out = subprocess.run(["exiftool", "-@", "-", "-n", "-csv", "-q", "-q", *(f"-{t}" for t in TAGS.values())],
                         input="\n".join(map(str, paths)), capture_output=True, text=True, check=True).stdout
    found = {}
    for r in csv.DictReader(io.StringIO(out)):
        path = Path(r["SourceFile"])
        found[path] = {"kind": "video" if path.suffix.lower() in VIDEO else "photo",
                       **{col: r.get(tag, "") for col, tag in TAGS.items()}}
    return found
