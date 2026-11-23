#!/usr/bin/env python3
"""Index clean/: what's there, where it came from, and what's in it.

Usage: build_index.py OUT_DIR

Writes, in OUT_DIR:
  files.csv    every file in clean/: its raw source, the cleaner that made it
               (empty for a symlink), size, modification time, and the indexers
               covering it. Diff it against an old copy to see what changed in raw/.
  <name>.csv   one per indexer: file, bytes, mtime, then the indexer's COLUMNS

Indexers are the modules in scripts/index/ whose names don't start with _
(those are helpers they can import). Each one has

  PATTERNS = ["photos/*.jpg"]   the files it covers, relative to clean/
  COLUMNS = ["taken", "lat", "lon"]
  def row(path):                a dict of COLUMNS for one file; missing ones are left empty

or, in place of row(), rows(paths) -> {path: dict}, to take many files in one go
(one exiftool call rather than thousands). Paths are absolute. Patterns ignore
case, and * matches across /.

A file's row is reused while its size and mtime are unchanged, unless the
indexer or a helper was edited after its CSV was written, so rerunning is cheap.
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from repo import BASE_DIR, CLEAN, edited, load_plugins, matches, visible_files

INDEXERS = BASE_DIR / "scripts/index"
SOURCES = CLEAN / ".sources.csv"
STAT = ["file", "bytes", "mtime"]
FILES = ["file", "source", "cleaner", "bytes", "mtime", "indexes"]


def read(path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["file"]: r for r in csv.DictReader(f)}


def write(path, columns, rows):
    tmp = path.with_name(f".tmp.{path.name}")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def stat(rel):
    """Size and mtime, of the raw file for a symlink."""
    st = (CLEAN / rel).stat()
    mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"file": f"clean/{rel}", "bytes": str(st.st_size), "mtime": mtime}


def index(name, module, files, out_dir):
    out = out_dir / f"{name}.csv"
    old = read(out) if out.exists() and out.stat().st_mtime >= edited(module) else {}
    covered = [rel for rel in files if matches(rel, module.PATTERNS)]
    rows, todo = {}, []
    for rel in covered:
        rows[rel] = stat(rel)
        prev = old.get(rows[rel]["file"])
        if prev and (prev["bytes"], prev["mtime"]) == (rows[rel]["bytes"], rows[rel]["mtime"]):
            rows[rel] = prev
        else:
            todo.append(rel)
    if todo:
        paths = [CLEAN / rel for rel in todo]
        found = module.rows(paths) if hasattr(module, "rows") else {p: module.row(p) for p in paths}
        for rel, path in zip(todo, paths):
            rows[rel].update(found.get(path) or {})
        print(f"{name}: {len(todo)} indexed, {len(covered) - len(todo)} unchanged")
    write(out, STAT + module.COLUMNS, [rows[rel] for rel in covered])
    return covered


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.split("\n\n")[1])
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    files = visible_files(CLEAN)

    covering = {rel: [] for rel in files}
    indexers = load_plugins(INDEXERS)
    for name, module in indexers.items():
        if not hasattr(module, "PATTERNS") or not hasattr(module, "COLUMNS") \
                or not (hasattr(module, "row") or hasattr(module, "rows")):
            sys.exit(f"scripts/index/{name}.py needs PATTERNS, COLUMNS, and row() or rows()")
        for rel in index(name, module, files, out_dir):
            covering[rel].append(name)

    sources = read(SOURCES)
    rows = []
    for rel in files:
        row = stat(rel)
        source = sources.get(row["file"], {})
        rows.append(row | {"source": source.get("source", ""), "cleaner": source.get("cleaner", ""),
                           "indexes": " ".join(covering[rel])})
    write(out_dir / "files.csv", FILES, rows)

    for path in out_dir.glob("*.csv"):
        if path.stem not in indexers and path.name != "files.csv":
            print(f"removed {path}, as its indexer is gone")
            path.unlink()
    unindexed = sum(not names for names in covering.values())
    print(f"index: {len(files)} files, {unindexed} not covered by an indexer")


if __name__ == "__main__":
    main()
