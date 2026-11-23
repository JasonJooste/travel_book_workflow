"""Paths and helpers shared by the scripts."""
import importlib.util
import os
import sys
from fnmatch import fnmatchcase
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW = BASE_DIR / "raw"
CLEAN = BASE_DIR / "clean"


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
