#!/usr/bin/env python3
"""The review app: one server, one page, a view for each kind of answer you give.

Usage: server.py [--story NAME] [--no-open]

Serves http://localhost:<review.port>/ on this machine only, and opens it in the browser. The page
holds no data: it asks for it here, so what a make target rebuilds shows on reload, and the app's
Rebuild button runs the target itself.

  GET  /                          the app (scripts/review/static/)
  GET  /api/settings              the travel modes, their colours, the classes, the trip's dates
  GET  /api/status                each built output, and whether your answers changed since
  POST /api/rebuild {"target"}    run that make target in the background; GET /api/rebuild?since=N
                                  says how it's going, with its output from line N
  GET  /api/rows/TABLE            a CSV of manual/ as rows (stays, travel_modes, known_places,
                                  dismissed, ignored_photos, place_picks, tags)
  POST /api/change {"why", "ops"} change rows of those, or save or drop a reviewed diary entry,
                                  together: one step for Undo (see store.py)
  POST /api/undo                  undo the last change; GET /api/changes lists the recent ones
  GET  /api/offsets               the UTC offsets through the trip, for local times on the map
  GET  /api/route/..., /api/stays/..., /api/places, /api/diary/..., /api/tags/..., /api/story/...
                                  each view's data: see the modules in scripts/review/api/
  GET  /api/thumb?f=clean/photos/X  a small JPEG of a photo or video, made once into processing/thumbs
  GET  /files/clean/..., /files/processing/audio/...   photos and recordings, with Range requests

Errors are plain text with their status: 400 for something that isn't valid, 404 for something
that isn't there, 409 when a row changed since the page loaded it.
"""
import argparse
import hashlib
import http.server
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import status  # noqa: E402
import store  # noqa: E402
from api import diary, places, route, stays, story  # noqa: E402
from repo import BASE_DIR, CLEAN, COMPRESSED, THUMBS  # noqa: E402
from settings import settings  # noqa: E402
from shared import offset_table  # noqa: E402
from store import Refused  # noqa: E402

STATIC = HERE / "static"
SERVED = [CLEAN, COMPRESSED]  # what /files/ may serve
THUMB_PX = 400
MARKER = b"travel_book review app"


def thumb(query):
    """JPEG bytes of a small version of a photo or video under clean/photos, made once."""
    asked = (parse_qs(query).get("f") or [""])[0]
    rel = os.path.normpath(asked)
    if not rel.startswith("clean/photos/") or ".." in Path(rel).parts:
        raise Refused(403, "only photos under clean/photos")
    src = BASE_DIR / rel
    if not src.is_file():
        raise Refused(404, "no such photo")
    st = src.stat()
    key = hashlib.sha1(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}\0{THUMB_PX}".encode()).hexdigest()
    out = THUMBS / key[:2] / f"{key}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name(f".tmp.{threading.get_ident()}.{out.name}")
        if src.suffix.lower() in (".mp4", ".mov", ".3gp", ".webm", ".mkv"):
            for at in ("1", "0"):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", at, "-i", str(src), "-frames:v", "1",
                                "-vf", f"scale='min({THUMB_PX},iw)':-2", "-f", "image2", str(part)], capture_output=True)
                if part.exists() and part.stat().st_size:
                    break
            if not part.exists():
                raise Refused(500, "ffmpeg made no frame")
        else:
            from PIL import Image, ImageOps
            try:
                with Image.open(src) as im:
                    im.draft("RGB", (THUMB_PX * 2, THUMB_PX * 2))  # JPEGs decode at a fraction of their size
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((THUMB_PX, THUMB_PX))
                    im.convert("RGB").save(part, "JPEG", quality=80)
            except OSError as e:
                raise Refused(500, f"can't read the photo: {e}")
        os.replace(part, out)
    return out.read_bytes()


def app_settings():
    return {"modes": {m: v.model_dump() for m, v in settings.modes.items()}, "classes": settings.classes,
            "colours": settings.colours, "trip": {"start": settings.trip.start.isoformat(), "end": settings.trip.end.isoformat()},
            "stay_radius_km": settings.stays.radius_km, "languages": settings.transcribe.languages}


def change(body):
    data = json.loads(body or b"{}")
    ops = data.get("ops") or []
    for op in ops:  # a diary entry's record is checked, and given its file, before it's saved
        if "entry" in op and op.get("op") == "put":
            op["record"] = diary.record_for_save(*op["entry"], op["record"])
    return store.change(str(data.get("why") or "a change"), ops)


def api(method, path, query, body, headers):
    """The data for an /api/ request, or (code, bytes, headers) for one that isn't JSON."""
    parts = [unquote(p) for p in path.strip("/").split("/")][1:]
    head, rest = (parts[0] if parts else ""), parts[1:]
    if head == "ping":
        return 200, MARKER, {"Content-Type": "text/plain"}
    if head == "settings" and method == "GET":
        return app_settings()
    if head == "status" and method == "GET":
        return status.status()
    if head == "rebuild":
        if method == "POST":
            try:
                return status.rebuild(json.loads(body or b"{}").get("target", ""))
            except (ValueError, RuntimeError) as e:
                raise Refused(409, str(e))
        return status.job(int((parse_qs(query).get("since") or ["0"])[0]))
    if head == "rows" and method == "GET" and len(rest) == 1:
        if rest[0] not in store.TABLES:
            raise Refused(404, f"no table {rest[0]}")
        return store.rows(rest[0])
    if head == "change" and method == "POST":
        return change(body)
    if head == "undo" and method == "POST":
        return store.undo()
    if head == "changes" and method == "GET":
        return store.recent()
    if head == "offsets" and method == "GET":
        return offset_table()
    if head == "pluscode" and method == "GET":
        from openlocationcode import openlocationcode as olc
        q = parse_qs(query)
        return {"code": olc.encode(float(q["lat"][0]), float(q["lon"][0]))}
    if head == "thumb" and method == "GET":
        return 200, thumb(query), {"Content-Type": "image/jpeg", "Cache-Control": "max-age=86400"}
    modules = {"route": route, "stays": stays, "places": places, "diary": diary, "tags": diary}
    if head in modules:
        out = modules[head].handle(method, parts if head in ("diary", "tags") else rest, query, body)
        if out is not None:
            return out
    if head == "story":
        out = story.handle(method, rest, query, body, headers)
        if out is not None:
            return out
    raise Refused(404, f"no such thing: {method} {path}")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # quiet: changes are printed as they're saved
        pass

    def send(self, code, data, headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):  # the page moved on
                pass

    def handle_any(self):
        path, _, query = self.path.partition("?")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if self.command in ("POST", "PUT") else b""
        try:
            if path.startswith("/api/"):
                out = api(self.command, path, query, body, self.headers)
                if isinstance(out, tuple):
                    return self.send(*out)
                return self.send(200, json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"),
                                 {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"})
            if self.command not in ("GET", "HEAD"):
                raise Refused(405, "not allowed")
            if path.startswith("/files/"):
                return self.file(BASE_DIR / unquote(path[len("/files/"):]), allowed=SERVED)
            return self.file(STATIC / (unquote(path.lstrip("/")) or "index.html"), allowed=[STATIC])
        except Refused as e:
            self.send(e.code, json.dumps({"error": str(e), **(e.data or {})}).encode(),
                      {"Content-Type": "application/json; charset=utf-8"})
        except Exception as e:  # say what broke, and keep serving
            import traceback
            traceback.print_exc()
            self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(),
                      {"Content-Type": "application/json; charset=utf-8"})

    do_GET = do_POST = do_HEAD = handle_any

    def file(self, path, allowed):
        """A file under one of allowed (not following links out of it: clean/ is links to raw/), with Range."""
        path = Path(os.path.abspath(path))
        if not any(path.is_relative_to(a) for a in allowed) or not path.is_file():
            raise Refused(404, "no such file")
        size = path.stat().st_size
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            kind = "text/javascript"
        headers = {"Content-Type": kind, "Accept-Ranges": "bytes",
                   "Cache-Control": "no-cache" if path.is_relative_to(STATIC) else "max-age=3600"}
        asked = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if not asked or not any(asked.groups()):
            return self.send(200, path.read_bytes(), headers)
        first, last = asked.groups()
        start, end = (int(first), min(int(last), size - 1) if last else size - 1) if first else (max(0, size - int(last)), size - 1)
        if start > end:
            return self.send(416, b"", {"Content-Range": f"bytes */{size}"})
        with path.open("rb") as f:
            f.seek(start)
            data = f.read(end - start + 1)
        self.send(206, data, {**headers, "Content-Range": f"bytes {start}-{end}/{size}"})


def running(port):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return r.read() == MARKER
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n")[1])
    parser.add_argument("--story")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    port = settings.review.port
    url = f"http://localhost:{port}/" + (f"#/story/{args.story}" if args.story else "")
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        if running(port):
            print(f"The review app is already running: {url}")
            if not args.no_open:
                webbrowser.open(url)
            return
        sys.exit(f"Port {port} is in use by something else: try SETTINGS_REVIEW__PORT={port + 1} make review")
    print(f"The review app: {url}  (Ctrl+C stops it). What you change saves to manual/ as you go.")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
