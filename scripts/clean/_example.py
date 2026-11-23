"""Example cleaner. Copy it to a name without the leading _ (e.g. front_matter.py) to use it.

Strips YAML front matter from markdown notes, so clean/notes/*.md is just the text.
"""
import re

PATTERNS = ["notes/*.md"]

FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def clean(src, dst):
    text = src.read_text(encoding="utf-8")
    dst.write_text(FRONT_MATTER.sub("", text), encoding="utf-8")
