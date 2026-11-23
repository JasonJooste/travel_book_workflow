#!/usr/bin/env python3
"""Merge the recorded rides (Komoot, Strava, ...) into one time-sorted track.

Usage: track.py

Reads every ride in clean/gpx (make clean-data). Where rides overlap, one point a minute is
kept. Points outside the trip (settings trip.start..end, UTC days) are dropped, to leave out
rides from before or after it.

Writes, in processing/track:
  points.csv     utc,lat,lon, at most one point a minute
  offsets.csv    utc,offset_min: each ride's start and the phone's UTC offset then, in minutes,
                 for turning local times into UTC. Strava writes every time in UTC, so its
                 rides give none
  coverage.txt   gaps between rides of track_gap_days or more
  track.png      the whole track, coloured by date, to check by eye
"""
import sys
from datetime import datetime, timezone

from common.tables import write_rows, write_text
from common.times import stamp
from common.track import gives_offsets, ride_points
from repo import GPX, TRACK
from settings import settings


def plot(points, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 10))
    sc = ax.scatter([p[1][1] for p in points], [p[1][0] for p in points],
                    c=[p[0].timestamp() for p in points], s=0.5, cmap="viridis")
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    bar = fig.colorbar(sc, ax=ax, shrink=0.6)
    ticks = bar.get_ticks()
    bar.set_ticks(ticks, labels=[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m") for t in ticks])
    tmp = path.with_name(f".tmp.{path.name}")
    fig.savefig(tmp, dpi=120, bbox_inches="tight", format="png")
    tmp.replace(path)


def main():
    if len(sys.argv) != 1:
        sys.exit(__doc__.split("\n\n")[1])
    start, end = settings.trip.start, settings.trip.end
    # One point per minute is plenty to place a diary entry
    by_minute, offsets = {}, []
    for path in sorted(GPX.rglob("*.gpx")):
        with_offsets = gives_offsets(path)
        for ride in ride_points(path):
            first = with_offsets
            for utc, lat, lon, offset in ride:
                if not start <= utc.date() <= end:
                    continue
                by_minute.setdefault(utc.replace(second=0, microsecond=0), (lat, lon))
                if first and offset is not None:
                    offsets.append((utc, offset))
                    first = False
    points = sorted(by_minute.items())
    if not points:
        sys.exit(f"no ride points in {GPX} within the trip: run make clean-data")

    write_rows(TRACK / "points.csv", ["utc", "lat", "lon"], ([stamp(utc), lat, lon] for utc, (lat, lon) in points))
    write_rows(TRACK / "offsets.csv", ["utc", "offset_min"],
               ([stamp(utc), round(offset.total_seconds() / 60)] for utc, offset in sorted(offsets)))

    gap = settings.track_gap_days
    gaps = [(a[0], b[0]) for a, b in zip(points, points[1:]) if (b[0] - a[0]).days >= gap]
    days = {utc.date() for utc, _ in points}
    lines = [f"{len(points)} points on {len(days)} days, {points[0][0]:%Y-%m-%d} to {points[-1][0]:%Y-%m-%d}",
             f"gaps of {gap}+ days ({len(gaps)}):"]
    lines += [f"  {a:%Y-%m-%d} -> {b:%Y-%m-%d}  ({(b - a).days} days)" for a, b in gaps]
    write_text(TRACK / "coverage.txt", "\n".join(lines) + "\n")
    print("\n".join(lines[:2]), f"see {TRACK / 'coverage.txt'}")
    plot(points, TRACK / "track.png")


if __name__ == "__main__":
    main()
