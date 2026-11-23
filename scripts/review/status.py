"""Whether each built output is behind your answers, and rebuilding it from the app.

An output is stale when a file it's built from changed after it was built: the route after a stay,
a travel mode row or a known place; the findings after the route or a dismissal. status() says so
for each, with the changes since, and the make target that brings it up to date. rebuild() runs that
target in the background, one at a time, and job() says how it's going.
"""
import subprocess
import threading
import time
from datetime import datetime

from repo import (BASE_DIR, DISMISSED_CSV, FINDINGS, FOUND_STAYS, IGNORED_PHOTOS_CSV, KNOWN_PLACES_CSV, LOCATED,
                  MODES_CSV, PLACE_PICKS_CSV, PLACES_CSV, REVIEWED_EVENTS, ROUTE, STAYS_CSV, TAGS_CSV, rel)
from store import changed_since

EVENTS_CSV = BASE_DIR / "processing/events/events.csv"
# Each output: what it's called, its file, the files it's built from, and the target that rebuilds it
OUTPUTS = {
    "places": ("Known places", PLACES_CSV, [KNOWN_PLACES_CSV, PLACE_PICKS_CSV], "places"),
    "route": ("The route", ROUTE / "route.csv", [STAYS_CSV, MODES_CSV, PLACES_CSV, KNOWN_PLACES_CSV, IGNORED_PHOTOS_CSV],
              "check"),
    "findings": ("The findings", FINDINGS, [ROUTE / "route.csv", DISMISSED_CSV, MODES_CSV, KNOWN_PLACES_CSV], "check"),
    "stays": ("The stays found", FOUND_STAYS, [], "stays"),
    "located": ("Where entries were", LOCATED / "audio.csv", [ROUTE / "route.csv", PLACES_CSV], "locate"),
    "events": ("The events index", EVENTS_CSV, [TAGS_CSV], "events ARGS=--limit=0"),
}


def mtime(path):
    if path.is_dir():
        return max((p.stat().st_mtime for p in path.rglob("*.json")), default=0)
    return path.stat().st_mtime if path.exists() else 0


def status():
    out = {}
    for key, (name, output, inputs, target) in OUTPUTS.items():
        built = mtime(output)
        if key == "events":
            inputs = [TAGS_CSV, REVIEWED_EVENTS]
        newer = [rel(p) for p in inputs if mtime(p) > built]
        changes = changed_since(built, [rel(p) for p in inputs]) if built else []
        out[key] = {"name": name, "built": datetime.fromtimestamp(built).isoformat(timespec="minutes") if built else None,
                    "stale": bool(newer) or not built, "newer": newer, "target": target,
                    "changes": [{"at": c["at"], "why": c["why"]} for c in changes]}
    return out


_job, _lock = {}, threading.Lock()


def rebuild(target):
    allowed = {t for *_, t in OUTPUTS.values()}
    if target not in allowed:
        raise ValueError(f"not a target the app rebuilds: {target}")
    with _lock:
        if _job.get("running"):
            raise RuntimeError(f"make {_job['target']} is still running")
        _job.clear()
        _job.update(target=target, running=True, lines=[], started=time.time(), code=None)

    def run():
        process = subprocess.Popen(["make", *target.split()], cwd=BASE_DIR, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            with _lock:
                _job["lines"].append(line.rstrip("\n"))
        code = process.wait()
        with _lock:
            _job.update(running=False, code=code, finished=time.time())
        print(f"make {target}: {'done' if code == 0 else f'failed ({code})'}", flush=True)

    threading.Thread(target=run, daemon=True).start()
    return job()


def job(since=0):
    with _lock:
        if not _job:
            return None
        return {**{k: v for k, v in _job.items() if k != "lines"}, "lines": _job["lines"][since:],
                "line_count": len(_job["lines"])}
