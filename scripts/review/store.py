"""Your answers in manual/, changed a row at a time, with undo.

Every change the review app makes goes through change(): a list of operations on the CSVs (add,
update or delete a row, by its id) and the reviewed diary entries (put or drop one), applied
together, checked, and saved with the files' old versions kept in manual/.history. Each change is
one entry in the log (manual/.history/changes.jsonl), which undo() steps back through: Undo in
the app puts every file the last change touched back as it was.

An update or delete names the row as the app last saw it (base): if the file now holds something
else there (changed in an editor, or in another tab), the change is refused with 409 and the row as
it is now, rather than overwriting it.
"""
import csv
import io
import json
import re
import secrets
import threading
from datetime import date, datetime

from common.tables import read_json, save_manual
from repo import (DISMISSED_CSV, HISTORY, IGNORED_PHOTOS_CSV, KNOWN_PLACES_CSV, MODES_CSV, PLACE_PICKS_CSV,
                  REVIEWED_EVENTS, STAYS_CSV, TAGS_CSV, rel)
from settings import settings

LOG = HISTORY / "changes.jsonl"
MERGE_SECONDS = 90  # saves of one file for one reason this close together are one change, to undo at once
LOCK = threading.RLock()


class Refused(Exception):
    def __init__(self, code, why, data=None):
        super().__init__(why)
        self.code, self.data = code, data


def check_date(value, what):
    try:
        date.fromisoformat(value)
    except ValueError:
        raise Refused(400, f"{what} should be YYYY-MM-DD, not {value!r}")


def check_stay(r):
    from openlocationcode import openlocationcode as olc
    check_date(r["first_night"], "first night")
    check_date(r["leaving"], "leaving")
    if r["leaving"] <= r["first_night"]:
        raise Refused(400, "leaving must be after the first night")
    if r["plus_code"] and not olc.isFull(r["plus_code"]):
        raise Refused(400, f"{r['plus_code']} isn't a full plus code")


def check_mode(r):
    if r["mode"] not in settings.modes:
        raise Refused(400, f"mode {r['mode']!r} isn't one of {', '.join(settings.modes)}")
    for k in ("start", "end"):
        if r[k] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?", r[k]):
            raise Refused(400, f"{k} should be YYYY-MM-DD or YYYY-MM-DDTHH:MM (UTC), not {r[k]!r}")
    if not r["start"]:
        raise Refused(400, "a travel mode row needs a start")
    if r["end"] and r["end"] < r["start"]:
        raise Refused(400, "end is before start")


def check_place(r):
    check_date(r["start_date"], "start date")
    if r["end_date"]:
        check_date(r["end_date"], "end date")
    if r["time"] and not re.fullmatch(r"\d{2}:\d{2}(:\d{2})?Z?", r["time"]):
        raise Refused(400, f"time should be HH:MM[:SS], local, or with Z for UTC: not {r['time']!r}")
    if bool(r["lat"]) != bool(r["lon"]):
        raise Refused(400, "a point needs both lat and lon")
    if not (r["lat"] or (r["town"] and r["country"])):
        raise Refused(400, "a known place needs a town and country, or its own lat and lon")


def check_tag(r):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", r["tag"]):
        raise Refused(400, f"a tag is lower-case letters, digits and _: not {r['tag']!r}")
    if not r["description"]:
        raise Refused(400, f"{r['tag']} needs a description")


# Each CSV: its path, its columns, the column that identifies a row, and its check
TABLES = {
    "stays": (STAYS_CSV, ["id", "first_night", "leaving", "town", "plus_code", "notes", "checked", "found"], "id", check_stay),
    "travel_modes": (MODES_CSV, ["id", "start", "end", "mode", "note"], "id", check_mode),
    "known_places": (KNOWN_PLACES_CSV, ["id", "start_date", "end_date", "time", "town", "country", "note", "lat", "lon"],
                     "id", check_place),
    "dismissed": (DISMISSED_CSV, ["id", "check", "start_utc", "end_utc", "lat", "lon", "note"], "id", None),
    "ignored_photos": (IGNORED_PHOTOS_CSV, ["file", "note"], "file", None),
    "place_picks": (PLACE_PICKS_CSV, ["town", "country", "geonameid", "name", "lat", "lon"], None, None),
    "tags": (TAGS_CSV, ["tag", "description"], "tag", check_tag),
}


def rows(name):
    path, fields, _, _ = TABLES[name]
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (r.get(k) or "").strip() for k in fields} for r in csv.DictReader(f)]


def text(name, table):
    _, fields, _, _ = TABLES[name]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(table)
    return out.getvalue()


def key_of(name, row):
    _, _, key, _ = TABLES[name]
    return row.get(key) if key else (row.get("town", "").lower(), row.get("country", ""))


def entry_path(kind, stem):
    path = (REVIEWED_EVENTS / kind / f"{stem}.json").resolve()
    if not path.is_relative_to(REVIEWED_EVENTS.resolve()) or "/" in stem:
        raise Refused(400, "not an entry")
    return path


def apply(op, tables, entries):
    """Apply one operation to the tables (name -> rows) or entries (path -> record or None) in memory."""
    if "table" in op:
        name = op["table"]
        if name not in TABLES:
            raise Refused(400, f"no table {name}")
        _, fields, key, check = TABLES[name]
        if name not in tables:
            tables[name] = rows(name)
            if key == "id":  # rows added by hand get their ids with the next change to the file
                for r in tables[name]:
                    r["id"] = r["id"] or secrets.token_hex(4)
        table = tables[name]
        kind = op.get("op")
        if kind == "add":
            row = {k: str(op["row"].get(k, "") or "").strip() for k in fields}
            if key == "id" and not row["id"]:
                row["id"] = secrets.token_hex(4)
            if check:
                check(row)
            if key and any(r[key] == row[key] for r in table):
                raise Refused(409, f"{name} already has {row[key]}")
            if not key:  # a pick replaces the one before for the same town
                table[:] = [r for r in table if key_of(name, r) != key_of(name, row)]
            table.append(row)
            return row
        found = next((r for r in table if key_of(name, r) == (op.get("key") or op.get("id"))), None)
        if found is None:
            raise Refused(409, f"that row of {name} isn't there any more: reload", {"current": None})
        if op.get("base") and any(str(op["base"].get(k, "")).strip() != found[k] for k in op["base"] if k in fields):
            raise Refused(409, f"that row of {name} changed since you loaded it", {"current": found})
        if kind == "update":
            new = {**found, **{k: str(v or "").strip() for k, v in op["row"].items() if k in fields and k != key}}
            if check:
                check(new)
            found.update(new)
            return found
        if kind == "delete":
            table.remove(found)
            return found
        raise Refused(400, f"no operation {kind!r}")
    if "entry" in op:
        kind, stem = op["entry"]
        path = entry_path(kind, stem)
        if op.get("op") == "put":
            entries[path] = op["record"]
        elif op.get("op") == "drop":
            entries[path] = None
        else:
            raise Refused(400, f"no operation {op.get('op')!r}")
        return op.get("record")
    raise Refused(400, "an operation needs a table or an entry")


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_log(log):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG.with_name(f".tmp.{LOG.name}")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in log[-500:]), encoding="utf-8")
    tmp.replace(LOG)


def change(why, ops):
    """Apply ops together, save the files they touch, and log it as one change. Returns
    {"id", "results": [the row or record each op touched]}."""
    with LOCK:
        tables, entries = {}, {}
        results = [apply(op, tables, entries) for op in ops]
        files = []
        for name, table in tables.items():
            path = TABLES[name][0]
            if name == "tags":
                used = reviewed_tags()
                if gone := used - {r["tag"] for r in table}:
                    raise Refused(400, f"still on events you reviewed: {', '.join(sorted(gone))}; take it off them first")
            new = text(name, table)
            kept = save_manual(path, new) if (not path.exists() or path.read_text(encoding="utf-8") != new) else False
            if kept is not False:
                files.append({"path": rel(path), "was": rel(kept) if kept else None})
        for path, record in entries.items():
            if record is None:
                if path.exists():
                    from common.tables import delete_manual
                    files.append({"path": rel(path), "was": rel(delete_manual(path))})
                continue
            record = {**record, "saved": datetime.now().isoformat(timespec="seconds")}
            kept = save_manual(path, json.dumps(record, ensure_ascii=False, indent=1) + "\n")
            files.append({"path": rel(path), "was": rel(kept) if kept else None})
        if not files:
            return {"id": None, "results": results}
        log = read_log()
        now = datetime.now()
        last = log[-1] if log else None
        if (last and not last.get("undone") and last["why"] == why and [f["path"] for f in last["files"]] == [f["path"] for f in files]
                and (now - datetime.fromisoformat(last["at"])).total_seconds() < MERGE_SECONDS):
            last["at"] = now.isoformat(timespec="seconds")  # the first snapshot is what undo goes back to
            entry = last
        else:
            entry = {"id": secrets.token_hex(4), "at": now.isoformat(timespec="seconds"), "why": why, "files": files}
            log.append(entry)
        write_log(log)
        print(f"{now:%H:%M:%S} {why}: {', '.join(f['path'] for f in files)}", flush=True)
        return {"id": entry["id"], "results": results}


def undo():
    """Put back the files of the last change not yet undone, as they were before it."""
    with LOCK:
        log = read_log()
        entry = next((e for e in reversed(log) if not e.get("undone")), None)
        if not entry:
            raise Refused(404, "nothing to undo")
        from repo import BASE_DIR
        from common.tables import delete_manual
        for f in reversed(entry["files"]):
            path = BASE_DIR / f["path"]
            if f["was"]:
                save_manual(path, (BASE_DIR / f["was"]).read_text(encoding="utf-8"))
            else:
                delete_manual(path)
        entry["undone"] = datetime.now().isoformat(timespec="seconds")
        write_log(log)
        print(f"undid: {entry['why']}", flush=True)
        return entry


def recent(n=30):
    return list(reversed(read_log()))[:n]


def changed_since(stamp, prefixes):
    """Changes (not undone) after a time (a POSIX timestamp) to files whose paths start with prefixes."""
    return [e for e in read_log() if not e.get("undone") and datetime.fromisoformat(e["at"]).timestamp() > stamp
            and any(f["path"].startswith(p) for f in e["files"] for p in prefixes)]


def reviewed_tags():
    """Tags on the events of entries reviewed by hand."""
    used = set()
    for path in REVIEWED_EVENTS.rglob("*.json"):
        for event in (read_json(path) or {}).get("events", []):
            used.update(event.get("tags", []))
    return used

