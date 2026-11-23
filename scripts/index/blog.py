"""Blog posts, which have no date, and Komoot tour descriptions (make fetch-komoot), each with its words.

A description is blog_posts/komoot/<local date>_<tour id>.txt: kind komoot, with its date and tour.
"""
import re

PATTERNS = ["blog_posts/*"]
COLUMNS = ["kind", "date", "tour", "words"]
KOMOOT = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.txt$")


def row(path):
    words = len(path.read_text(encoding="utf-8").split())
    if path.parent.name == "komoot" and (m := KOMOOT.match(path.name)):
        return {"kind": "komoot", "date": m[1], "tour": m[2], "words": words}
    return {"kind": "blog", "date": "", "tour": "", "words": words}
