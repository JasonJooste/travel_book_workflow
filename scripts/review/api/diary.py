"""The Diary and Tags views' data: each entry with its audio, text and events; the tag list.

  GET  /api/diary                   every entry make events covers: kind, date, place, words, events,
                                    and whether you've reviewed it (edited) or verified it
  GET  /api/diary/KIND/STEM         one entry: its facts, its audio, its text in pieces (timed, where the
                                    transcript has timings), its events and the tags Claude suggested
  GET  /api/tags                    the tag list, with how many events carry each tag and each pair
  POST /api/tags/overlap            ask Claude which tags overlap in meaning ({"candidate": {tag,
                                    description}} for a new one: does it repeat one in the list?)

Saving goes through /api/change (store.py): an entry's events go to manual/events/KIND/STEM.json,
which make events then uses as saved and never sends to Claude again; the tags to manual/tags.csv.
"""
import json
import re
import subprocess
from collections import Counter
from datetime import date
from itertools import combinations
from pathlib import Path
from urllib.parse import quote

from common.llm import LimitReached, RetryableError, structured
from events import KINDS, answer, entries, entry_text, read_tags
from repo import COMPRESSED, rel
from store import Refused

INFO = ["file", "local_date", "utc", "date_source", "town", "country", "lat", "lon", "position_source",
        "duration_min", "transcript_source", "words", "language"]
EVENT_TEXTS, EVENT_LISTS = ["title", "summary", "date", "place", "quote"], ["people", "tags"]

OVERLAP_PROMPT = """\
You check the list of tags used to index the events of a travel diary: a two-year bicycle trip \
from Europe through West and Central Africa to South Africa, indexed for the book its author \
is writing. Each tag has a description and the number of events that carry it so far.

Find the pairs of tags that overlap: an event that fits one would nearly always fit the other, \
or the two descriptions leave it unclear which to use. Tags that often go together but mean \
different things (a breakdown and its fix) do not overlap. For each pair give a one-sentence \
reason and a one-sentence suggestion: merge them, narrow one (say how), or keep both. Give no \
pairs if none overlap.
"""
OVERLAP_SHAPE = {
    "type": "object", "additionalProperties": False, "required": ["pairs"],
    "properties": {"pairs": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["a", "b", "reason", "suggestion"],
        "properties": {k: {"type": "string"} for k in ("a", "b", "reason", "suggestion")}}}}}


def find(kind, stem):
    for e in entries():
        if e["kind"] == kind and e["cache"].stem == stem:
            return e
    raise Refused(404, f"no entry {kind}/{stem}: make locate lists the entries, make events the ones with words")


def status(entry, record):
    if not entry["manual"].exists():
        return ""
    return "verified" if record.get("verified") else "edited"


def listing():
    out = []
    for e in entries():
        record = answer(e) or {}
        out.append({"kind": e["kind"], "stem": e["cache"].stem, "date": e["local_date"], "utc": e["utc"],
                    "town": e["town"], "country": e["country"], "words": int(e["words"]),
                    "events": len(record["events"]) if record else None, "status": status(e, record),
                    "titles": [x["title"] for x in record.get("events", [])][:6]})
    return out


def seconds(entry, audio):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return float(entry.get("duration_min") or 0) * 60


def segments(entry, audio):
    """The entry's text as [start, end, text] pieces, and where the times are from: "transcript" (its
    own timings), "approximate" (the recording's length shared among the pieces by their length,
    until it has a timed transcript: drifts by seconds) or "" (no times: written text)."""
    if entry["text"].suffix == ".json":
        timed = json.loads(entry["text"].read_text(encoding="utf-8")).get("segments")
        if timed:
            return [[s["start"], s["end"], s["text"].strip()] for s in timed], "transcript"
    pieces = [p.strip() for p in re.split(r"\n+|\s{2,}" if audio else r"\n+", entry_text(entry)) if p.strip()]
    if not audio:
        return [[None, None, p] for p in pieces], ""
    total, length, at, out = sum(len(p) for p in pieces) or 1, seconds(entry, audio), 0, []
    for p in pieces:
        out.append([round(at / total * length, 1), round((at + len(p)) / total * length, 1), p])
        at += len(p)
    return out, "approximate"


def entry_data(entry):
    record = answer(entry) or {}
    stem = entry["cache"].stem
    audio = COMPRESSED / f"{stem}.ogg" if entry["kind"] == "audio" else None
    if audio and not audio.exists():
        audio = None
    pieces, timing = segments(entry, audio)
    cached = json.loads(entry["cache"].read_text(encoding="utf-8")) if entry["cache"].exists() else {}
    tags = read_tags()
    return {"kind": entry["kind"], "kind_name": KINDS.get(entry["kind"], entry["kind"]), "stem": stem,
            "info": {k: entry.get(k, "") for k in INFO}, "text_file": rel(entry["text"]),
            "audio": "/files/" + quote(rel(audio)) if audio else "", "segments": pieces, "timing": timing,
            "events": record.get("events") or [], "language": record.get("language", ""),
            "verified": bool(record.get("verified")), "note": record.get("note", ""),
            "status": status(entry, record), "has_llm": bool(cached), "model": cached.get("model", ""),
            "suggested": [s for s in cached.get("suggested_tags", []) if s["name"] not in tags]}


def clean_record(entry, data):
    """An entry's record as the app sends it, checked: its events' fields, dates and tags."""
    tags, events = read_tags(), []
    if not isinstance(data.get("events"), list):
        raise Refused(400, "events should be a list")
    for n, e in enumerate(data["events"], 1):
        if not (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in EVENT_TEXTS)
                and all(isinstance(e.get(k), list) and all(isinstance(x, str) for x in e[k]) for k in EVENT_LISTS)):
            raise Refused(400, f"event {n} is not text fields plus lists of people and tags")
        e = {**{k: e[k].strip() for k in EVENT_TEXTS}, **{k: [x.strip() for x in e[k] if x.strip()] for k in EVENT_LISTS},
             "date_guessed": bool(e.get("date_guessed"))}
        if not e["title"]:
            raise Refused(400, f"event {n} has no title")
        if e["date"]:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]):
                    raise ValueError
                date.fromisoformat(e["date"])
            except ValueError:
                raise Refused(400, f"event {n}: the date {e['date']} is not YYYY-MM-DD")
        if unknown := set(e["tags"]) - set(tags):
            raise Refused(400, f"event {n}: not in the tag list: {', '.join(sorted(unknown))}")
        events.append({k: e[k] for k in ("title", "summary", "date", "place", "people", "tags", "quote")}
                      | {"date_guessed": e["date_guessed"] and bool(e["date"])})
    return {"file": entry["file"], "kind": entry["kind"], "language": str(data.get("language") or ""),
            "verified": bool(data.get("verified")), "note": str(data.get("note") or "").strip(), "events": events}


def usage():
    counts, pairs, events = Counter(), Counter(), 0
    for e in entries():
        for event in (answer(e) or {}).get("events", []):
            events += 1
            counts.update(set(event["tags"]))
            pairs.update(combinations(sorted(set(event["tags"])), 2))
    return {"events": events, "counts": counts, "pairs": [[a, b, n] for (a, b), n in pairs.most_common(40)]}


def tags():
    from store import reviewed_tags
    used = usage()
    from repo import EVENTS
    from common.tables import read_rows
    suggested = read_rows(EVENTS / "suggested_tags.csv")
    current = read_tags()
    return {"tags": [{"tag": t, "description": d, "events": used["counts"].get(t, 0)} for t, d in current.items()],
            "events": used["events"], "pairs": used["pairs"], "reviewed": sorted(reviewed_tags()),
            "suggested": [s for s in suggested if s["tag"] not in current]}


def overlap(body):
    data = json.loads(body or b"{}")
    candidate, current, counts = data.get("candidate"), read_tags(), usage()["counts"]
    text = "Tags:\n" + "\n".join(f"- {t} ({counts.get(t, 0)} events): {d}" for t, d in current.items())
    if candidate:
        name, description = (str(candidate.get(k) or "").strip() for k in ("tag", "description"))
        text += (f"\n\nA new tag is proposed:\n- {name}: {description}\n\n"
                 f"Give only the pairs that include {name}: the tags in the list it overlaps with.")
    try:
        return structured(OVERLAP_PROMPT, text, OVERLAP_SHAPE, backend="cli")
    except (LimitReached, RetryableError, RuntimeError) as e:
        raise Refused(502, f"Claude didn't answer: {e}")


def handle(method, parts, query, body):
    if parts[:1] == ["diary"]:
        if method == "GET" and parts == ["diary"]:
            return listing()
        if method == "GET" and len(parts) == 3:
            return entry_data(find(parts[1], parts[2]))
    if parts[:1] == ["tags"]:
        if method == "GET" and parts == ["tags"]:
            return tags()
        if method == "POST" and parts == ["tags", "overlap"]:
            return overlap(body)
    return None


def record_for_save(kind, stem, data):
    """The checked record to save for an entry, from what the app sends."""
    return clean_record(find(kind, stem), data)


__all__ = ["handle", "record_for_save", "Path"]
