"""Example indexer, one file at a time. Copy it to a name without the leading _ (e.g. words.py) to use it.

Word count and title of each markdown or text file.
"""
PATTERNS = ["*.md", "*.txt"]
COLUMNS = ["words", "title"]


def row(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    first = next((line for line in text.splitlines() if line.strip()), "")
    return {"words": len(text.split()), "title": first.lstrip("# ").strip()}
