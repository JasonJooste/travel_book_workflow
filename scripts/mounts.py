#!/usr/bin/env python3
"""Read-only mounts of raw data that lives outside the repo.

Usage: mounts.py configure|mount|unmount|status

configure asks for each mount point (a directory under raw/, e.g. raw/diary)
and the directory to mount there, and writes them to mounts.toml. That file
and the mount points are machine-specific, so both go in .git/info/exclude:
they never reach a commit, and nothing about them is pushed upstream.

mount uses bindfs -r, so no sudo is needed and nothing in the repo (make,
scripts, an editor) can change the originals through the mount.

Each mount really sits under the hidden .mounts/ (raw/diary at .mounts/diary),
and the mount point is a symlink to it. File managers list FUSE mounts under
the home directory in their sidebar, but leave out any below a hidden
directory. bindfs can't take x-gvfs-hide (libfuse 2 rejects x- options), and
that option only works through mount(8) and fstab, which need sudo.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW = BASE_DIR / "raw"
CONFIG = BASE_DIR / "mounts.toml"
EXCLUDE = BASE_DIR / ".git" / "info" / "exclude"
HIDDEN = BASE_DIR / ".mounts"
EXCLUDE_HEADER = "# Local raw data mounts (scripts/mounts.py)"


def load():
    if not CONFIG.exists():
        return {}
    with CONFIG.open("rb") as f:
        return tomllib.load(f).get("mounts", {})


def save(mounts):
    # JSON strings are valid TOML basic strings
    lines = [
        "# Read-only mounts of raw data kept outside the repo, local to this machine.",
        "# Written by `make mounts`; mount with `make mount`.",
        "",
        "[mounts]",
    ]
    lines += [f"{json.dumps(point)} = {json.dumps(source)}" for point, source in mounts.items()]
    CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def exclude(paths):
    """Keep the config and mount points out of git without touching .gitignore."""
    text = EXCLUDE.read_text(encoding="utf-8") if EXCLUDE.exists() else ""
    # Rewrite our own block, leaving anything else in the file alone
    kept = text.split(EXCLUDE_HEADER)[0].rstrip("\n")
    # No trailing /: the mount points are symlinks, which git doesn't count as directories
    block = [EXCLUDE_HEADER] + [f"/{p}" for p in paths] + ["/.mounts/", "/mounts.toml"]
    new = (kept + "\n\n" if kept else "") + "\n".join(block) + "\n"
    if new != text:
        EXCLUDE.write_text(new, encoding="utf-8")


def target(point):
    """Where the mount for point really is: raw/diary at .mounts/diary."""
    return HIDDEN / Path(point).relative_to("raw")


def linked(point):
    """Whether point is the symlink to its mount."""
    link = BASE_DIR / point
    return link.is_symlink() and os.readlink(link) == os.path.relpath(target(point), link.parent)


def is_mounted(point):
    return linked(point) and os.path.ismount(target(point))


def tracked(point):
    out = subprocess.run(["git", "-C", BASE_DIR, "ls-files", "--", point],
                         capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


def check_point(point, others):
    """Return a problem with mount point `point`, or None."""
    # Not resolved: once mounted, point is a symlink out of raw/
    path = Path(os.path.abspath(BASE_DIR / point))
    if not path.is_relative_to(RAW) or path == RAW:
        return "must be a directory under raw/"
    if re.search(r"\s", point):
        return "has whitespace, which make can't handle"
    if any(path.is_relative_to(BASE_DIR / o) or (BASE_DIR / o).is_relative_to(path) for o in others):
        return "overlaps another mount point"
    if tracked(point):
        return "git already tracks files there"
    if linked(point):
        return None
    if os.path.ismount(path):
        return "is mounted in place (the old layout): run make unmount, then make mount"
    if path.is_symlink():
        return "is a symlink to somewhere else"
    if path.is_dir() and any(path.iterdir()):
        return "already holds files, which the mount would hide"
    if path.exists() and not path.is_dir():
        return "is a file"
    return None


def ask(prompt, default=""):
    answer = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
    return answer or default


def configure():
    mounts = {}
    for point, source in load().items():
        if ask(f"Keep {point} <- {source}? (y/n)", "y").lower().startswith("y"):
            mounts[point] = source
    print("Add mounts. Leave the mount point blank to finish.")
    while True:
        point = ask("Mount point under raw/ (e.g. raw/diary)").strip("/")
        if not point:
            break
        point = os.path.normpath(point)
        if problem := check_point(point, mounts):
            print(f"  {point} {problem}")
            continue
        source = Path(ask("Directory to mount there")).expanduser().resolve()
        if not source.is_dir():
            print(f"  {source} is not a directory")
            continue
        if source.is_relative_to(BASE_DIR):
            print("  source must live outside the repo")
            continue
        mounts[point] = str(source)
    save(mounts)
    exclude(mounts)
    print(f"Wrote {len(mounts)} mount(s) to {CONFIG.name}. Run `make mount` to mount them.")


def mount():
    mounts = load()
    if mounts:
        # Also brings the excludes of a project set up before .mounts/ up to date
        exclude(mounts)
    for point, source in mounts.items():
        if is_mounted(point):
            continue
        if not shutil.which("bindfs"):
            sys.exit("bindfs is missing: run `make apt`")
        if problem := check_point(point, set(mounts) - {point}):
            sys.exit(f"{point} {problem}")
        if not Path(source).is_dir():
            sys.exit(f"{point}: source {source} is not a directory")
        link, hidden = BASE_DIR / point, target(point)
        hidden.mkdir(parents=True, exist_ok=True)
        if not os.path.ismount(hidden):
            subprocess.run(["bindfs", "-r", "--no-allow-other", source, hidden], check=True)
        if not linked(point):
            # check_point made sure anything already there is an empty directory
            if link.is_dir():
                link.rmdir()
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(os.path.relpath(hidden, link.parent))
        print(f"mounted {point} <- {source} (read-only)")


def unmount():
    for point in load():
        link, hidden = BASE_DIR / point, target(point)
        # The point itself is a mount if it was set up before .mounts/
        for path in (hidden, link):
            if os.path.ismount(path):
                subprocess.run(["fusermount", "-u", path], check=True)
                print(f"unmounted {point}")
        # Leave no dangling symlink or empty mount point behind
        if linked(point):
            link.unlink()
        for path in (hidden, link):
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
    if HIDDEN.is_dir():
        for dirpath, _, _ in os.walk(HIDDEN, topdown=False):
            if not os.listdir(dirpath) and not os.path.ismount(dirpath):
                os.rmdir(dirpath)


def unmounted():
    """Configured mount points that aren't mounted."""
    return [point for point in load() if not is_mounted(point)]


def status():
    mounts = load()
    if not mounts:
        print("no mounts configured; run `make mounts`")
    for point, source in mounts.items():
        state = "mounted" if is_mounted(point) else "not mounted"
        print(f"{point} <- {source}: {state}")


def main():
    commands = {"configure": configure, "mount": mount, "unmount": unmount, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__.split("\n\n")[1])
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
