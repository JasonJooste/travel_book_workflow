#!/usr/bin/env python3
"""What happened in each diary entry: Claude splits it into events and tags them.

Usage: events.py [--dry-run] [--limit N] [--files NAME ...] [--redo-stale]

  --dry-run     count the entries to do, done and stale, and their words (and the cost, with the api
                backend); call nothing
  --limit N     only the first N entries still to do
  --files       only these entries, by file name (of the recording, not its transcript)
  --redo-stale  also redo entries done with an older tag list, glossary or prompt

The backend, model, workers and so on are under events in settings.yaml: backend cli uses the
Claude subscription (claude -p); api is paid.

Entries are the recordings' transcripts, the written diary, the blog posts and the Komoot
descriptions, as make locate lists them, of events.min_words or more. Each goes to Claude once;
its answer is kept in processing/events/entries/KIND/<stem>.json, so a run can be stopped (or stop
itself, at the subscription's usage limit) and started again. Then, from every answer kept:
  processing/events/events.csv          one row per event; tags and people are ;-separated. date is
                                        the day it happened, counted back from when the entry was
                                        made; date_guessed says the entry didn't say when
  processing/events/suggested_tags.csv  tags Claude would add to manual/tags.csv, most suggested first
Claude puts a tag it suggests on the events it fits, but it stays out of events.csv until it's in
manual/tags.csv: add it there (or with New tag in the review app's Tags view) and its events have it.

An entry reviewed in the review app's Diary view is in manual/events/KIND/<stem>.json. Its events
are used as saved, marked in the reviewed column, and it is never sent to Claude again.
"""
import argparse
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from common.llm import BACKENDS, LimitReached, RetryableError, structured
from common.tables import read_rows as rows, write_json, write_rows, write_text
from common.times import Offsets, track_offsets
from repo import BASE_DIR, EVENT_ENTRIES, EVENTS, GLOSSARY, LOCATED, REVIEWED_EVENTS, TAGS_CSV, rel
from settings import settings

E = settings.events
KINDS = {"audio": "spoken diary entry, transcribed by machine", "written": "written diary entry",
         "blog": "blog post", "komoot": "description written for a day's ride on Komoot"}
FIELDS = ["event_id", "date", "entry_date", "utc", "lat", "lon", "town", "country", "kind", "file",
          "language", "title", "summary", "place", "people", "tags", "quote", "date_guessed", "reviewed"]
LANGUAGE_NAMES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese"}


def languages():
    names = [LANGUAGE_NAMES.get(code, code) for code in settings.transcribe.languages]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


PROMPT = """\
You index the diary of a two-year bicycle trip ({start:%B %Y} to {end:%B %Y}) from Europe \
through West and Central Africa to South Africa, for the book its author is writing. You are given one entry: a spoken diary \
entry transcribed by machine, a written one, a blog post or a short ride description. \
Entries are in {languages}.

Split the entry into events: the separate things that happened, each one something the author \
might later look for. A meeting, a breakdown, a border, a night somewhere, a conversation and \
a stretch of thinking something through are each an event. Most entries hold one to six; a long \
one can hold more. Leave out filler and anything too slight to look for later; an entry that \
says nothing gets no events.

For each event:
- title: a few words.
- summary: two to four sentences in English, whatever the entry's language, in the first \
person as the author ("I"), naming the people and places so that a text search finds them. \
Say what happened, not how the entry or its transcript reads.
- ago: how long before the entry was made the event happened, as days and hours: 0d2h is two \
hours before, 2d0h two days before, 0d0h as the entry is made. Work it out from what the entry \
says ("this morning", "yesterday", "on Tuesday", "three days ago") and from when the entry was \
made. Where the entry doesn't say, give your best guess from the order it tells things in and \
whatever else it gives.
- ago_guessed: true if the day it happened is such a guess. False if the entry says or plainly \
implies which day ("today", "this morning", "yesterday", "on Tuesday", or simply the day's \
events told on that day), even when the hour is only rough.
- date: only when the entry itself gives the event's calendar date, as YYYY-MM-DD; otherwise \
empty. The author writes dates as yy-mm-dd: 25-06-23 is 23 June 2025. For an entry with no \
date of its own this is the only date there is, and ago is 0d0h.
- place: where it happened, if the entry names the place or it plainly happened where the \
entry was made. Empty otherwise: don't guess.
- people: the names of the people who took part or are talked about, not the author, and not \
public figures or writers he only read or heard.
- tags: the tags from the list below whose description fits this event itself, not just \
something it mentions in passing. Hold each tag to its description: a tag about other people \
is not for the author, and a tag about something happening (a border crossed, a breakdown) is \
not for plans or memories of it. The tags for feelings are for when the entry shows the \
feeling was strong, not for every good or bad moment. Many events get no tag. A tag you \
propose in suggested_tags goes here too, on the events it fits. Use no other tags.
- quote: one short line copied exactly from the entry, in its language, to find the passage by.

In suggested_tags, propose a tag only for a theme of this entry that the book could use, that \
would come up in many other entries too, and that no tag in the list covers: a short, general \
snake_case name and a description in the list's style. Put it in the tags of the events it \
fits, as for a tag from the list. Usually there are none.

Machine transcripts mishear names. Where a word is clearly one of the known names below, or \
the town the entry was made in, spell it that way. Leave a name alone when it is a different \
name that merely resembles a known one: Marie is not Maria.

Tags:
{tags}

Known names:
{glossary}
"""



def read_tags():
    """Description by tag name."""
    return {r["tag"].strip(): r["description"].strip() for r in rows(TAGS_CSV)}


def schema(tags):
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False}
    text, texts = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
    event = obj({"title": text, "summary": text, "ago": text, "ago_guessed": {"type": "boolean"},
                 "date": text, "place": text, "people": texts,
                 "tags": texts, "quote": text})  # from the list or suggested_tags: checked in extract
    suggestion = obj({"name": text, "description": text})
    return obj({"language": {"type": "string", "enum": list(settings.transcribe.languages)},
                "events": {"type": "array", "items": event},
                "suggested_tags": {"type": "array", "items": suggestion}})


def entries():
    """Every located entry with text: its row, plus kind, text, cache and manual (paths)."""
    found = []
    for name in ("audio", "written", "blog"):
        for r in rows(LOCATED / f"{name}.csv"):
            text = r["transcript"] if name == "audio" else r["file"]
            if not text or int(r["words"] or 0) < E.min_words:
                continue
            kind = r.get("kind") or name
            stem = Path(r["file"]).stem
            found.append({**r, "kind": kind, "text": BASE_DIR / text,
                          "cache": EVENT_ENTRIES / kind / f"{stem}.json",
                          "manual": REVIEWED_EVENTS / kind / f"{stem}.json"})
    if len({e["cache"] for e in found}) < len(found):
        sys.exit("two entries of one kind share a file name")
    return found


def entry_text(entry):
    """The entry's words. A provider's transcript is JSON, with them under text."""
    raw = entry["text"].read_text(encoding="utf-8")
    return json.loads(raw)["text"] if entry["text"].suffix == ".json" else raw


def answer(entry):
    """The entry's events as saved by hand, else as Claude gave them, else None.

    A tag Claude suggests is in the tags of the events it fits, as a tag from the list is. Answers
    kept before that listed the events' numbers (from 1) with the suggestion: they're put on them here.
    """
    for path in (entry["manual"], entry["cache"]):
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            for s in record.get("suggested_tags", []):
                for n in s.pop("events", []):
                    if 1 <= n <= len(record["events"]) and s["name"] not in record["events"][n - 1]["tags"]:
                        record["events"][n - 1]["tags"].append(s["name"])
            return record
    return None


def made_at(entry, offsets):
    """(when the entry was made in local time, whether the time of day is known); None without a date.

    Only a recording has a time. Without one it's taken as the end of its day.
    """
    if not entry["local_date"]:
        return None, False
    day = date.fromisoformat(entry["local_date"])
    if entry["kind"] == "audio" and entry.get("utc"):
        utc = datetime.strptime(entry["utc"], "%Y-%m-%dT%H:%MZ")
        local = utc + offsets.at(utc)
        if local.date() == day:
            return local, True
    return datetime.combine(day, datetime.max.time()), False


def dated(event, made):
    """The event with its day worked out: date, and date_guessed, from Claude's ago and date."""
    # Claude sometimes adds minutes (0d2h30m, 0d1h30); they're kept rather than failing the entry
    ago = re.fullmatch(r"(\d+)d(\d+)h(?:(\d+)m?)?", event["ago"].strip())
    if not ago:
        raise RuntimeError(f"ago should be like 2d0h, not {event['ago']!r}")
    guessed = event.pop("ago_guessed")
    if event["date"]:
        try:
            date.fromisoformat(event["date"])
        except ValueError:
            raise RuntimeError(f"date should be YYYY-MM-DD, not {event['date']!r}")
        guessed = False
    elif made:
        event["date"] = (made - timedelta(days=int(ago[1]), hours=int(ago[2]), minutes=int(ago[3] or 0))).date().isoformat()
    else:
        guessed = False
    return {**event, "date_guessed": guessed}


def extract(entry, system, shape, version, tags, offsets):
    """Ask Claude about one entry and keep its answer."""
    place = ", ".join(x for x in (entry["town"], entry["country"]) if x)
    made, timed = made_at(entry, offsets)
    when = (f"{made:%Y-%m-%d %H:%M} local time, a {made:%A}" if timed
            else f"{made:%Y-%m-%d}, a {made:%A}; time of day unknown" if made else "unknown")
    # A Komoot description is placed at the start of its ride, and is mostly about what came after
    where = "Ride started in" if entry["kind"] == "komoot" else "Made in"
    text = (f"Kind: {KINDS[entry['kind']]}\nMade: {when}\n"
            f"{where}: {place or 'unknown'}\n\n{entry_text(entry)}")
    retries = bad = 0
    while True:
        try:
            answer = structured(system, text, shape)
            proposed = {x["name"] for x in answer["suggested_tags"]}
            if unknown := {t for e in answer["events"] for t in e["tags"]} - set(tags) - proposed:
                raise RuntimeError("tags not in the list or suggested_tags: " + ", ".join(sorted(unknown)))
            answer["events"] = [dated(e, made) for e in answer["events"]]
            break
        except RetryableError:
            retries += 1
            if retries == E.retries:
                raise
            time.sleep(2 ** retries * 5)
        except RuntimeError:  # a bad answer gets one more try
            bad += 1
            if bad == 2:
                raise
    record = {"file": entry["file"], "kind": entry["kind"], "backend": E.backend,
              "model": BACKENDS[E.backend].model, "version": version,
              "transcript_source": entry.get("transcript_source", ""), **answer}
    write_json(entry["cache"], record)


def build(found, tags):
    """events.csv and suggested_tags.csv, from every answer kept."""
    events, suggested, unknown = [], {}, {}
    for entry in found:
        record = answer(entry)
        if record is None:
            continue
        stem = entry["cache"].stem
        reviewed = ("verified" if record.get("verified") else "edited") if entry["manual"].exists() else ""
        proposed = {s["name"]: s for s in record.get("suggested_tags", []) if s["name"] not in tags}
        on = {name: [] for name in proposed}
        for n, e in enumerate(record["events"], 1):
            # A suggested tag stays off the index until it's in the list; once it is, its events have it
            kept = e["tags"] if reviewed else [t for t in e["tags"] if t in tags]
            events.append({**{k: entry.get(k, "") for k in FIELDS}, **e, "event_id": f"{stem}#{n}",
                           "entry_date": entry["local_date"], "language": record.get("language", ""),
                           "people": ";".join(e["people"]), "tags": ";".join(kept),
                           "date_guessed": "yes" if e.get("date_guessed") else "", "reviewed": reviewed})
            for t in set(e["tags"]) - set(tags):
                if t in on and not reviewed:
                    on[t].append(f"{stem}#{n}")
                elif reviewed:
                    unknown.setdefault(t, []).append(f"{stem}#{n}")
        for name, s in proposed.items():
            tag = suggested.setdefault(name, {"description": s["description"], "events": []})
            tag["events"] += on[name] or [stem]
    events.sort(key=lambda e: (e["date"] or e["entry_date"] or "9999", e["utc"], e["event_id"]))
    n = write_rows(EVENTS / "events.csv", FIELDS, [[e[k] for k in FIELDS] for e in events])
    print(f"{rel(EVENTS / 'events.csv')}: {n} events")
    write_rows(EVENTS / "suggested_tags.csv", ["tag", "description", "count", "example_event_ids"],
               [(name, s["description"], len(s["events"]), ";".join(s["events"][:5]))
                for name, s in sorted(suggested.items(), key=lambda kv: (-len(kv[1]["events"]), kv[0]))])
    for t, ids in sorted(unknown.items()):
        print(f"tag {t} is not in {rel(TAGS_CSV)} but is on reviewed events: {', '.join(ids)}")


def prompt():
    """(system prompt, schema, version, tags). Answers made with another prompt, tag list or glossary
    are stale: their version differs."""
    tags = read_tags()
    # The glossary as it is, comment lines and all: changing that would make every answer stale
    glossary = GLOSSARY.read_text(encoding="utf-8").strip() if GLOSSARY.exists() else "(none)"
    system = PROMPT.format(tags="\n".join(f"- {name}: {d}" for name, d in tags.items()), glossary=glossary,
                           start=settings.trip.start, end=settings.trip.end, languages=languages())
    shape = schema(tags)
    version = hashlib.sha256((system + json.dumps(shape)).encode()).hexdigest()[:12]
    return system, shape, version, tags


def main():
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n")[1])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--files", nargs="+")
    parser.add_argument("--redo-stale", action="store_true")
    args = parser.parse_args()

    system, shape, version, tags = prompt()
    offsets = Offsets(track_offsets())  # local time through the trip
    found = entries()
    chosen = found
    if args.files:
        if missing := set(args.files) - {Path(e["file"]).name for e in found}:
            sys.exit("not found (or under %d words): %s" % (E.min_words, ", ".join(sorted(missing))))
        chosen = [e for e in found if Path(e["file"]).name in args.files]
    reviewed = [e for e in chosen if e["manual"].exists()]  # kept as saved, never redone
    new = [e for e in chosen if not e["cache"].exists() and not e["manual"].exists()]
    stale = [e for e in chosen if e["cache"].exists() and not e["manual"].exists()
             and json.loads(e["cache"].read_text(encoding="utf-8"))["version"] != version]
    todo = (stale + new if args.redo_stale else new)[:args.limit]
    words = sum(int(e["words"]) for e in todo)
    print(f"{len(chosen)} entries: {len(reviewed)} reviewed by hand, "
          f"{len(chosen) - len(new) - len(stale) - len(reviewed)} done, {len(stale)} stale"
          f"{'' if args.redo_stale or not stale else ' (--redo-stale redoes them)'}, {len(new)} new; "
          f"{len(todo)} to do now, {words} words")
    if args.dry_run:
        if E.backend == "api":
            # Rough: 1.4 tokens a word; an answer of 800 tokens (thinking included) plus 0.3 a word
            tokens_in = (words + len(todo) * len(system.split())) * 1.4
            tokens_out = len(todo) * 800 + words * 0.3
            usd_in, usd_out = BACKENDS["api"].usd_per_mtok
            print(f"roughly ${(tokens_in * usd_in + tokens_out * usd_out) / 1e6:.0f} with {E.api_model}")
        return

    stop, failures, done = threading.Event(), [], 0

    def one(entry):
        if stop.is_set():
            return "skipped"
        try:
            extract(entry, system, shape, version, tags, offsets)
        except LimitReached as e:
            if not stop.is_set():
                print(f"usage limit reached: {e}", flush=True)
            stop.set()
            return "skipped"

    started = time.monotonic()
    with ThreadPoolExecutor(E.workers) as pool:
        futures = {pool.submit(one, e): e for e in todo}
        for n, (future, entry) in enumerate(futures.items(), 1):
            try:
                if future.result() == "skipped":
                    continue
                done += 1
            except Exception as e:  # keep going; failures are logged, and a rerun tries them again
                failures.append(f"{entry['file']}\t{e}")
            eta = (time.monotonic() - started) / n * (len(todo) - n)
            print(f"{n}/{len(todo)}  eta {eta / 60:.0f} min  {Path(entry['file']).name}", flush=True)

    build(found, tags)
    if left := len(todo) - done - len(failures):
        print(f"stopped at the usage limit with {left} entries left: run again once it resets, "
              "or with SETTINGS_EVENTS__BACKEND=api")
    if failures:
        write_text(EVENTS / "failures.log", "\n".join(failures) + "\n")
        sys.exit(f"{len(failures)} failed; see {EVENTS / 'failures.log'}")


if __name__ == "__main__":
    main()
