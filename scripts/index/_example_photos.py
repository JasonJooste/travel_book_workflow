"""Example indexer, all files in one go. Copy it to a name without the leading _ (e.g. photos.py) to use it.

When and where each photo or video was taken, from one exiftool call
(add libimage-exiftool-perl to apt-requirements.txt). Lat/lon are signed decimals;
taken is the camera's local time.
"""
import csv
import io
import subprocess
from pathlib import Path

PATTERNS = ["*.jpg", "*.jpeg", "*.heic", "*.png", "*.mp4", "*.mov"]
COLUMNS = ["taken", "lat", "lon"]


def rows(paths):
    # File names on stdin (-@ -), as thousands of them would overflow the command line
    out = subprocess.run(
        ["exiftool", "-@", "-", "-n", "-csv", "-q", "-q", "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude"],
        input="\n".join(map(str, paths)), capture_output=True, text=True, check=True).stdout
    return {Path(r["SourceFile"]): {"taken": r.get("DateTimeOriginal", ""), "lat": r.get("GPSLatitude", ""),
                                    "lon": r.get("GPSLongitude", "")}
            for r in csv.DictReader(io.StringIO(out))}
