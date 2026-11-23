"""The written diary: each file's local date, from its name, and its words. Fragments and themes have no date.

Names start with the date, as 24_09_05_..., 2025_12_27_... or 26-07-14-...; some are day first.
Only a date within the trip counts.
"""
import re
from datetime import date

from settings import settings

PATTERNS = ["diary/written/*"]
COLUMNS = ["date", "words"]


def written_date(name):
    """The local date in a file name, or None."""
    if not (m := re.match(r"^(\d{2,4})[_-](\d{2})[_-](\d{2})", name)):
        return None
    a, b, c = (int(x) for x in m.groups())
    for y, mo, d in ((a, b, c), (c, b, a)):
        try:
            day = date(y if y > 100 else 2000 + y, mo, d)
        except ValueError:
            continue
        if settings.trip.start <= day <= settings.trip.end:
            return day
    return None


def row(path):
    day = written_date(path.name)
    return {"date": day.isoformat() if day else "", "words": len(path.read_text(encoding="utf-8").split())}
