"""When each diary recording was made, and how long it is.

Most WAVs carry an IDIT chunk: a little-endian Unix timestamp, so true UTC (date_source
wav_header). Otherwise the time comes from the file name, in local time (filename): make locate
makes it UTC. duration_min is from ffprobe.
"""
import re
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

PATTERNS = ["diary/audio/*.wav", "diary/audio/*.flac", "diary/audio/*.mp3", "diary/audio/*.m4a"]
COLUMNS = ["recorded", "date_source", "duration_min"]

# File name patterns, each giving a local time
FILENAME_PATTERNS = [
    (re.compile(r"^(\d{8})-(\d{4})_"), "%Y%m%d%H%M"),                 # 20250723-2245_entry_3.wav
    (re.compile(r"^Note_(\d{8})_(\d{4})_otter"), "%Y%m%d%H%M"),        # Note_20241105_1830_otter.ai.mp3
    (re.compile(r"^(\d{4}_\d{2}_\d{2})_(\d{2}_\d{2}_\d{2})\."), "%Y_%m_%d%H_%M_%S"),  # 2024_12_21_21_06_56.m4a
    (re.compile(r"^(\d{6})()\.wav$"), "%d%m%y"),                       # 170924.wav
]


def wav_timestamp(path):
    """UTC datetime from a WAV's IDIT chunk, or None."""
    with path.open("rb") as f:
        head = f.read(4096)
    if head[:4] != b"RIFF":
        return None
    i = 12
    while i + 8 <= len(head):
        chunk, size = head[i:i + 4], struct.unpack("<I", head[i + 4:i + 8])[0]
        if chunk == b"IDIT" and size >= 4:
            return datetime.fromtimestamp(struct.unpack("<I", head[i + 8:i + 12])[0], timezone.utc)
        if chunk == b"data":
            return None
        i += 8 + size + (size & 1)
    return None


def filename_date(name):
    """Local datetime from the file name, or None."""
    for pattern, fmt in FILENAME_PATTERNS:
        if m := pattern.match(name):
            return datetime.strptime(m[1] + m[2], fmt)
    return None


def recorded_at(path):
    """(datetime, source): wav_header (aware UTC), filename (naive local) or (None, "")."""
    if path.suffix.lower() == ".wav" and (dt := wav_timestamp(path)):
        return dt, "wav_header"
    if dt := filename_date(path.name):
        return dt, "filename"
    return None, ""


def duration_min(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout
    try:
        return f"{float(out) / 60:.1f}"
    except ValueError:  # N/A: a header ffprobe can't read the length from
        return ""


def row(path, minutes):
    dt, source = recorded_at(path)
    text = "" if dt is None else dt.strftime("%Y-%m-%dT%H:%M:%SZ" if source == "wav_header" else "%Y-%m-%dT%H:%M:%S")
    return {"recorded": text, "date_source": source, "duration_min": minutes}


def rows(paths):
    with ThreadPoolExecutor(8) as pool:
        minutes = list(pool.map(duration_min, paths))
    return {p: row(p, m) for p, m in zip(paths, minutes)}
