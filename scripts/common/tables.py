"""CSV and JSON files, read leniently and written safely.

Every output is written under a temporary name beside it and renamed into place, so an
interrupted run leaves nothing half-written. Files in manual/ are your answers: save_manual()
also keeps the version it replaces in manual/.history, which the review app's Undo goes back to.
"""
import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path

from repo import HISTORY, MANUAL

HISTORY_KEEP = 200  # versions kept per file in manual/.history


def read_rows(path, missing_ok=True):
    """The rows of a CSV as dicts, or [] if it's missing and that's allowed."""
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return []
        raise SystemExit(f"{path} is missing")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def csv_text(fields, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def write_text(path, text):
    """Write text to path through a temporary file, so it's never half-written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".tmp.{path.name}")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".tmp.{path.name}")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_rows(path, fields, rows):
    """Write dict rows (or lists, in field order) as a CSV, safely."""
    rows = [r if isinstance(r, dict) else dict(zip(fields, r)) for r in rows]
    write_text(path, csv_text(fields, rows))
    return len(rows)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data, indent=1):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


def history_dir(path):
    """Where the old versions of a file in manual/ are kept: manual/.history/<its path, no suffix>/."""
    rel = Path(path).resolve().relative_to(MANUAL.resolve())
    return HISTORY / rel.with_suffix("")


def history_name(path):
    """A new name in history_dir(path), by the time: <YYYYMMDD-HHMMSS-micro><suffix>, sorting in time order."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return history_dir(path) / f"{stamp}{Path(path).suffix}"


def save_manual(path, text):
    """Replace a file in manual/ with text, keeping the old version in manual/.history.
    Returns the history file written, or None for a new file."""
    path = Path(path)
    kept = None
    if path.exists():
        old = path.read_bytes()
        if old == text.encode("utf-8"):
            return None
        kept = history_name(path)
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(old)
        versions = sorted(kept.parent.iterdir())
        for stale in versions[:-HISTORY_KEEP]:
            stale.unlink()
    write_text(path, text)
    return kept


def delete_manual(path):
    """Remove a file in manual/, keeping it in manual/.history."""
    path = Path(path)
    if not path.exists():
        return None
    kept = history_name(path)
    kept.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, kept)
    return kept
