"""Paths and helpers shared by the scripts."""
import importlib.util
import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW = BASE_DIR / "raw"
CLEAN = BASE_DIR / "clean"

# The project's layout. Paths aren't settings: settings.yaml holds what you'd tune
PROCESSING = BASE_DIR / "processing"
MANUAL = BASE_DIR / "manual"           # your answers, written by hand or through the review app; in git
HISTORY = MANUAL / ".history"          # every earlier version of a file the review app changed
INDEX = PROCESSING / "index"           # per-file facts about clean/ (make index)

# Inputs in clean/
GPX = CLEAN / "gpx"
KOMOOT_TOURS = GPX / "komoot_tours.csv"
PHOTOS = CLEAN / "photos"
AUDIO = CLEAN / "diary/audio"
WRITTEN = CLEAN / "diary/written"
BLOG = CLEAN / "blog_posts"
STORIES = CLEAN / "stories"
RAW_STORIES = RAW / "stories"          # read directly only for the replay logs (make progress)

# Your files
STAYS_CSV = MANUAL / "stays.csv"
MODES_CSV = MANUAL / "travel_modes.csv"
KNOWN_PLACES_CSV = MANUAL / "known_places.csv"
PLACE_PICKS_CSV = MANUAL / "place_picks.csv"
DISMISSED_CSV = MANUAL / "dismissed.csv"
IGNORED_PHOTOS_CSV = MANUAL / "ignored_photos.csv"
REVIEWED_EVENTS = MANUAL / "events"
TAGS_CSV = MANUAL / "tags.csv"
GLOSSARY = MANUAL / "glossary.txt"
PILOT = MANUAL / "pilot.txt"
STORY_PLANS = BASE_DIR / "story_plans"

# Outputs, by step
TRACK = PROCESSING / "track"
TRACK_POINTS = TRACK / "points.csv"
TRACK_OFFSETS = TRACK / "offsets.csv"
GEONAMES = PROCESSING / "geonames"
CITIES = GEONAMES / "cities500.txt"
PLACES = PROCESSING / "places"
PLACES_CSV = PLACES / "places.csv"
PLACE_QUESTIONS = PLACES / "questions.json"
STAYS = PROCESSING / "stays"
FOUND_STAYS = STAYS / "found.json"
OSM = PROCESSING / "osm"
VALHALLA_CONFIG = OSM / "valhalla/valhalla.json"
WATERWAYS = OSM / "waterways.geojsonseq"
ROUTE = PROCESSING / "route"
FINDINGS = ROUTE / "findings.json"
LOCATED = PROCESSING / "located"
COMPRESSED = PROCESSING / "audio"
ASR = PROCESSING / "asr"
EVENTS = PROCESSING / "events"
EVENT_ENTRIES = EVENTS / "entries"
THUMBS = PROCESSING / "thumbs"
STORY_CHECKS = PROCESSING / "story/checks"


def rel(path):
    """path relative to the repo, as the CSVs and the review app name files. Symlinks aren't
    followed: clean/photos/x.jpg stays itself, not the raw file it points at."""
    return Path(os.path.abspath(path)).relative_to(BASE_DIR).as_posix()


def visible_files(root):
    """Every file under root as a sorted path relative to it, leaving out hidden files and directories."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = Path(dirpath).relative_to(root)
        files += [(rel / f).as_posix() for f in filenames if not f.startswith(".")]
    return sorted(files)


def matches(rel, patterns):
    """Whether rel matches a glob in patterns, ignoring case. * matches across /, so *.jpg is any jpg."""
    return any(fnmatchcase(rel.lower(), p.lower()) for p in patterns)


def load_plugins(directory):
    """The modules in directory, by name, leaving out the helpers starting with _ (which they can import)."""
    sys.path.insert(0, str(directory))
    plugins = {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"{directory.name}_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugins[path.stem] = module
    return plugins


def edited(module):
    """When a plugin or any helper beside it was last edited, so editing either rebuilds its outputs."""
    path = Path(module.__file__)
    return max(p.stat().st_mtime for p in [path, *path.parent.glob("_*.py")])
