#!/usr/bin/env python3
"""Replace whitespace in file and directory names under each DIR with _, as make can't handle it.

Usage: rename_spaces.py DIR... [--apply]
       rename_spaces.py --undo

make clean-data prints the command to run, with every DIR raw/ needs: raw
itself and the source of each raw/ mount (mounts are read-only), so this
renames your original files. Anything else that finds them by name (other
apps, sync tools, links, notes that mention them) will lose them.

Without --apply, only lists what it would rename. With it, asks once, then
renames, recording each rename in renames.csv in the current directory as it
goes. --undo puts back every name from the latest run in that file, newest
first, and takes them out of it.

Hidden files, mount points and symlinks to directories under a DIR are
left alone. Nothing is renamed
if any new name is already taken.
"""
import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

WHITESPACE = re.compile(r"\s")
LOG = Path("renames.csv").resolve()
COLUMNS = ["run", "dir", "old", "new"]
WARNING = """\
This renames the originals in these directories, not copies:
{dirs}
Anything else that finds these files by name (other apps, sync tools, links,
notes that mention them) will lose them. Each rename is logged in
{log}, and running
  python3 scripts/rename_spaces.py --undo
from this directory puts the names back."""


def plan(root):
    """[(old, new)] relative to root, deepest first, so each path is valid when its turn comes."""
    renames = []
    # Top-down, so hidden directories, mounts and links to them (raw/ mount points)
    # are skipped with everything under them
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and not os.path.ismount(Path(dirpath, d)) and not os.path.islink(Path(dirpath, d))]
        rel = Path(dirpath).relative_to(root)
        for name in filenames + dirnames:
            if not name.startswith(".") and WHITESPACE.search(name):
                renames.append((rel / name, rel / WHITESPACE.sub("_", name)))
    # A directory is listed before what's in it, so reversed, its contents go first
    return renames[::-1]


def collisions(root, renames):
    new = [n for _, n in renames]
    return sorted({str(root / n) for n in new if (root / n).exists() or new.count(n) > 1})


def apply(plans, total):
    print(WARNING.format(dirs="\n".join(f"  {root}" for root in plans), log=LOG))
    if input(f"Rename {total} path(s)? [y/N] ").strip().lower() != "y":
        sys.exit("nothing renamed")
    run = datetime.now().isoformat(timespec="seconds")
    new_log = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new_log:
            writer.writerow(COLUMNS)
        for root, renames in plans.items():
            for old, new in renames:
                (root / old).rename(root / new)
                # Logged as each one happens, so an interrupted run can still be undone
                writer.writerow([run, root, old, new])
                f.flush()
    print(f"renamed {total}; undo with: python3 scripts/rename_spaces.py --undo, from this directory")


def undo():
    if not LOG.exists():
        sys.exit(f"no {LOG} to undo from")
    with LOG.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    run = rows[-1]["run"] if rows else None
    todo = [r for r in rows if r["run"] == run]
    kept = [r for r in rows if r["run"] != run]
    done, problem = 0, None
    for row in reversed(todo):
        old, new = Path(row["dir"], row["old"]), Path(row["dir"], row["new"])
        if not new.exists() or old.exists():
            problem = f"stopped after {done} of {len(todo)}: can't rename {new} back to {old}"
            break
        new.rename(old)
        done += 1
    # Whatever wasn't put back stays in the log, to retry
    kept += todo[:len(todo) - done]
    if kept:
        with LOG.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(kept)
    else:
        LOG.unlink()
    if problem:
        sys.exit(problem)
    print(f"renamed {done} back, from the run at {run}")


def main():
    args = sys.argv[1:]
    if args == ["--undo"]:
        return undo()
    roots = [Path(a).resolve() for a in args if a != "--apply"]
    if not roots or args.count("--apply") > 1 or any(a.startswith("--") and a != "--apply" for a in args):
        sys.exit(__doc__.split("\n\n")[1])
    for root in roots:
        if not root.is_dir():
            sys.exit(f"{root} is not a directory")
        if any(root != other and root.is_relative_to(other) for other in roots):
            sys.exit(f"{root} is inside another DIR given")
    plans = {root: renames for root in dict.fromkeys(roots) if (renames := plan(root))}
    total = sum(map(len, plans.values()))
    if not total:
        return print("no whitespace in names")
    taken = []
    for root, renames in plans.items():
        print(f"{root}:")
        for old, new in renames:
            print(f"  {old} -> {new.name}")
        taken += collisions(root, renames)
    if taken:
        sys.exit("nothing renamed, as these names are already taken:\n  " + "\n  ".join(taken))
    if "--apply" in args:
        apply(plans, total)
    else:
        print(f"{total} to rename; add --apply to do it")


if __name__ == "__main__":
    main()
