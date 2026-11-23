"""Stories as the book prints them: front matter and {{notes}} stripped."""
from _story_text import strip

PATTERNS = ["stories/*.md"]


def clean(src, dst):
    dst.write_text(strip(src.read_text(encoding="utf-8")), encoding="utf-8")
