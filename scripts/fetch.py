#!/usr/bin/env python3
"""Download the recorded Komoot tours: their GPX, and their sports, times and descriptions.

Usage: fetch.py gpx|meta

  gpx    each recorded tour as <date>_<id>.gpx, into the directory raw/gpx/komoot is mounted from.
         Planned routes are skipped (they carry no times), and so are tours already downloaded and
         unchanged
  meta   komoot_tours.csv (id,start_utc,end_utc,local_date,sport,name,km,changed_at), beside them, one
         row per recorded tour of the trip; end is the start plus Komoot's duration, so it takes in
         stops. Each tour with a description gets <local date>_<id>.txt in the directory
         raw/blog_posts/komoot is mounted from: its name, a blank line, then the description. A tour
         whose changed_at is as in the last komoot_tours.csv isn't fetched again

These are the only scripts that write raw data: raw/ itself is mounted read-only, so they write to
the directories it's mounted from (mounts.toml). The login is ~/.secrets/komoot_email and
~/.secrets/komoot_password, never the command line.
"""
import csv
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.tables import read_rows
from mounts import load as mounts
from settings import settings

FIELDS = ["id", "start_utc", "end_utc", "local_date", "sport", "name", "km", "changed_at"]


def source(point):
    """Where raw/<point> really lives, or exit: the mount's source, or raw/ itself."""
    for mount, src in mounts().items():
        if f"raw/{point}".startswith(mount + "/") or f"raw/{point}" == mount:
            return Path(src) / Path(f"raw/{point}").relative_to(mount)
    sys.exit(f"raw/{point} isn't in a mount: add it with make mounts")


def login():
    return settings.secret("komoot_email"), settings.secret("komoot_password")


def gpx():
    from komootgpx import komootgpx
    mail, password = login()
    out = source("gpx/komoot")
    out.mkdir(parents=True, exist_ok=True)
    # Pinned to komootgpx 1.6.2, whose login asks prompt() for the email and prompt_pass() for the
    # password when they aren't given as options: --pass would put it where ps shows it
    komootgpx.prompt = lambda title: mail
    komootgpx.prompt_pass = lambda title: password
    komootgpx.notify_interactive = lambda: None
    sys.argv = ["komootgpx", "--make-all", "--tour-type=recorded", "--skip-unchanged",
                "--filename-pattern={date}_{id}.gpx", f"--output={out}"]
    sys.exit(komootgpx.entrypoint())


def meta():
    import requests
    from komootgpx.api import KomootApi
    api = KomootApi()
    api.login(*login())
    tours = api.fetch_tours("tour_recorded").values()
    out_csv, desc_dir = source("gpx") / "komoot_tours.csv", source("blog_posts/komoot")
    old = {r["id"]: r for r in read_rows(out_csv)}
    desc_dir.mkdir(parents=True, exist_ok=True)

    def stamp(t):
        return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

    rows, fetched, written = [], 0, 0
    for tour in sorted(tours, key=lambda t: t["date"]):
        start = datetime.fromisoformat(tour["date"])
        local = start.date()
        if not settings.trip.start <= local <= settings.trip.end:
            continue
        tid = str(tour["id"])
        rows.append({"id": tid, "start_utc": stamp(start), "end_utc": stamp(start + timedelta(seconds=tour["duration"])),
                     "local_date": local.isoformat(), "sport": tour["sport"], "name": tour["name"],
                     "km": f"{tour['distance'] / 1000:.1f}", "changed_at": tour["changed_at"]})
        path = desc_dir / f"{local.isoformat()}_{tid}.txt"
        if old.get(tid, {}).get("changed_at") == tour["changed_at"]:
            continue
        if "description" not in tour:  # not always in the list: fetched on its own
            r = requests.get(f"https://api.komoot.de/v007/tours/{tid}", auth=(api.user_id, api.token))
            r.raise_for_status()
            tour = r.json()
        text = (tour.get("description") or "").strip()
        fetched += 1
        if text:
            path.write_text(f"{tour['name']}\n\n{text}\n", encoding="utf-8")
            written += 1
        elif path.exists():
            print(f"no description any more, so {path} is stale")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    part = out_csv.with_suffix(".csv.part")
    part.write_text(buffer.getvalue(), encoding="utf-8")
    part.replace(out_csv)
    print(f"{len(rows)} tours in {out_csv}; {fetched} new or changed, {written} descriptions written to {desc_dir}")


def main():
    commands = {"gpx": gpx, "meta": meta}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__.split("\n\n")[1])
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
