#!/usr/bin/env python3
"""Build clean/ from raw/: cleaned copies of the files a cleaner claims, symlinks to the rest.

Usage: build_clean.py

Cleaners are the modules in scripts/clean/ whose names don't start with _
(those are helpers they can import). Each one has

  PATTERNS = ["stories/*.md"]   the raw files it claims, relative to raw/
  def clean(src, dst):          writes the cleaned file dst from the raw file src

and optionally

  def dest(rel):                where the result goes, relative to clean/, if not rel
  DROP = True                   in place of clean(): leave the files it claims out

Patterns ignore case, and * matches across /. A file claimed by two cleaners is
an error. A cleaned file is rebuilt when it's older than its raw file, its
cleaner or a helper. Anything in clean/ that raw/ no longer accounts for is
removed, and clean/.sources.csv records where each file came from, for the index.

Refuses to run while a mount in mounts.toml is down, as clean/ would lose
everything from it, or while a raw path has whitespace, which make can't
handle: it says how to rename them with scripts/rename_spaces.py.
"""
import csv
import os
import re
import shlex
import sys
import traceback

from mounts import load, unmounted
from repo import BASE_DIR, CLEAN, RAW, edited, load_plugins, matches, visible_files

CLEANERS = BASE_DIR / "scripts/clean"
SOURCES = CLEAN / ".sources.csv"


def check_names(files):
    """Exit with the commands that rename raw paths with whitespace, run on the originals."""
    spaced = [rel for rel in files if re.search(r"\s", rel)]
    if not spaced:
        return
    mounts = load()
    dirs = set()
    for rel in spaced:
        point = next((p for p in mounts if f"raw/{rel}".startswith(f"{p}/")), None)
        # Mounts are read-only, so their files are renamed at the source
        dirs.add(mounts[point] if point else "raw")
    shown = [f"raw/{rel}" for rel in spaced[:10]] + [f"... and {len(spaced) - 10} more"] * (len(spaced) > 10)
    command = "python3 scripts/rename_spaces.py " + " ".join(shlex.quote(d) for d in sorted(dirs))
    sys.exit(f"{len(spaced)} raw path(s) have whitespace, which make can't handle:\n  " + "\n  ".join(shown)
             + f"\nSee what renaming them would do (nothing changes without --apply):\n  {command}")


def check(cleaners):
    for name, m in cleaners.items():
        if not hasattr(m, "PATTERNS") or not (hasattr(m, "clean") or getattr(m, "DROP", False)):
            sys.exit(f"scripts/clean/{name}.py needs PATTERNS, and clean() or DROP = True")


def plan(cleaners):
    """{dest: (rel, cleaner)} for every file clean/ should hold; cleaner is "" for a symlink."""
    planned, problems = {}, []
    files = visible_files(RAW)
    check_names(files)
    for rel in files:
        claims = [name for name, m in cleaners.items() if matches(rel, m.PATTERNS)]
        if len(claims) > 1:
            problems.append(f"raw/{rel} is claimed by {' and '.join(claims)}")
            continue
        name = claims[0] if claims else ""
        module = cleaners.get(name)
        if getattr(module, "DROP", False):
            continue
        dest = module.dest(rel) if hasattr(module, "dest") else rel
        if re.search(r"\s", dest):
            problems.append(f"{name}.dest() gives raw/{rel} a name with whitespace: {dest}")
            continue
        if dest in planned:
            problems.append(f"clean/{dest} would come from both raw/{planned[dest][0]} and raw/{rel}")
            continue
        planned[dest] = (rel, name)
    if problems:
        sys.exit("\n".join(problems))
    return planned


def link(src, dst):
    """Point dst at src with a relative symlink, unless it already does."""
    target = os.path.relpath(src, dst.parent)
    if dst.is_symlink() and os.readlink(dst) == target:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    dst.symlink_to(target)
    return True


def run(module, src, dst, newest):
    """Clean src into dst, unless dst is newer than src and the cleaner."""
    if not dst.is_symlink() and dst.exists() and dst.stat().st_mtime >= max(src.stat().st_mtime, newest):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Written beside dst under a hidden name, so an interrupted run leaves no half-written file.
    # Same extension, for tools that pick a format by it
    tmp = dst.with_name(f".tmp.{dst.name}")
    try:
        module.clean(src, tmp)
        if not tmp.exists():
            raise RuntimeError("wrote nothing (to leave files out, use DROP = True)")
    except BaseException:
        tmp.unlink(missing_ok=True)
        # Better missing than stale: nothing downstream reads an old version
        dst.unlink(missing_ok=True)
        raise
    tmp.replace(dst)
    return True


def prune(planned):
    removed = [rel for rel in visible_files(CLEAN) if rel not in planned]
    for rel in removed:
        (CLEAN / rel).unlink()
    for dirpath, _, _ in os.walk(CLEAN, topdown=False):
        if dirpath != str(CLEAN) and not os.listdir(dirpath):
            os.rmdir(dirpath)
    return removed


def write_sources(planned):
    with SOURCES.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["file", "source", "cleaner"])
        for dest, (rel, name) in sorted(planned.items()):
            writer.writerow([f"clean/{dest}", f"raw/{rel}", name])


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    if down := unmounted():
        sys.exit(f"not mounted: {', '.join(down)}. Run make mount, or clean/ would lose their files")
    cleaners = load_plugins(CLEANERS)
    check(cleaners)
    planned = plan(cleaners)
    newest = {name: edited(m) for name, m in cleaners.items()}

    CLEAN.mkdir(exist_ok=True)
    cleaned = linked = 0
    failed = []
    for dest, (rel, name) in planned.items():
        src, dst = RAW / rel, CLEAN / dest
        if not name:
            linked += link(src, dst)
            continue
        try:
            if run(cleaners[name], src, dst, newest[name]):
                print(f"{name}: clean/{dest}")
                cleaned += 1
        except Exception:
            print(f"{name} failed on raw/{rel}:", file=sys.stderr)
            traceback.print_exc()
            failed.append(f"raw/{rel}")
    for rel in prune(planned):
        print(f"removed stale clean/{rel}")
    write_sources(planned)

    if cleaned or linked:
        print(f"clean/: {cleaned} cleaned, {linked} linked")
    if failed:
        sys.exit(f"{len(failed)} failed: {' '.join(failed)}")


if __name__ == "__main__":
    main()
