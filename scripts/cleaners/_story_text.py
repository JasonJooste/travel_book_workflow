"""Story text without its front matter or {{notes}}: shared by the stories cleaner and make progress."""
import re

FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
# Take the space before an inline note too, so "melon {{phrasing}}." -> "melon."
NOTE = re.compile(r"[ \t]*\{\{.*?\}\}", re.DOTALL)


def strip(text):
    text = FRONT_MATTER.sub("", text)
    text = NOTE.sub("", text)
    lines = [line.strip() for line in text.splitlines()]
    # Notes on their own line leave blank runs behind; keep single blank lines
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip() + "\n"
