#!/usr/bin/env python3
"""Count words written and deleted, and estimate time to finish the book.

Usage: progress.py [--period day|week|month|all] [--plot] [REPLAY...]
       (default: writing.period in settings.yaml, raw/stories/.*.replay)

The period runs from the start of the current calendar day, week (Monday)
or month to now; "all" is the whole life of the logs.

Each log is replayed op by op, keeping the document as it goes. For every
op made in the period, the changed span is widened to whole words
and the words there before and after the op are diffed: new words count as
written, removed ones as deleted. Words typed and removed again later in
the period count in both. Changing a word (fixing a typo, finishing a word
begun in an earlier op) counts as one deleted and one written.

{{notes}} stand for editing still to do: each op's change in the number of
"{{" counts as notes added or resolved.

Time spent writing is counted in poms: edits less than writing.session_gap_min apart
form a session, and each session counts as its length in writing.pom_minutes,
rounded, at least one. From that it prints words per pom and per hour.

The time to finish comes from all sessions so far, not just the period.
Fitting  minutes = a * net_words + b * notes_resolved  over the sessions
gives a, time per word kept (drafting that's later cut included), and b,
time per note (rewriting to resolve it included). Drafting time is a times
the words still to go; editing time is b times the open notes plus the
notes drafting them will add, at the notes per net word so far. Drafting is
complete by words against the target; overall by time spent against time
spent plus time to finish. b stays unknown until there are
writing.min_edit_sessions sessions that resolved at least writing.min_notes_resolved
notes each. The settings are under writing in settings.yaml.

The replay logs are read from raw/stories itself (they're hidden files, which clean/ leaves out),
and the stories' words counted as the book prints them, without front matter or notes.

--plot also charts the running totals through the period and opens the image.
"""
import argparse
import difflib
import re
import subprocess
import sys
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "cleaners"))
from _story_text import strip as clean  # noqa: E402
from repo import RAW_STORIES  # noqa: E402
from settings import settings  # noqa: E402

W = settings.writing
CONFIG = {"POM_MINUTES": W.pom_minutes, "POMS_PER_DAY": W.poms_per_day, "TARGET_WORDCOUNT": W.target_words,
          "MIN_EDIT_SESSIONS": W.min_edit_sessions, "MIN_NOTES_RESOLVED": W.min_notes_resolved}

UNESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
OP = re.compile(rb"^(?:(\d+)\t)?(\d+)\t(\d+)\t(.*)$")
NOTE = b"{{"

# One op's effect. Untimed ops come from before the log had a header: they're
# older than any period but "all", and stamped with the epoch.
Event = namedtuple("Event", "when written deleted added resolved timed")


def unesc(s):
    return re.sub(rb"\\(.)", lambda m: UNESC.get(m[1].decode(), m[1].decode()).encode(), s)


def widen(doc, lo, hi):
    """Grow [lo, hi) outwards to whitespace, so it covers whole words."""
    while lo > 0 and not doc[lo - 1:lo].isspace():
        lo -= 1
    while hi < len(doc) and not doc[hi:hi + 1].isspace():
        hi += 1
    return lo, hi


def count(path):
    """Return an Event for every op that changed words or notes."""
    doc, epoch, events = b"", None, []
    for line in path.read_bytes().split(b"\n"):
        if epoch is None and line.startswith(b"#replayvim\tepoch\t"):
            epoch = int(line.split(b"\t")[2])
            continue
        m = OP.match(line)
        if not m:
            continue
        secs, off, dele, text = m[1], int(m[2]), int(m[3]), unesc(m[4])
        new = doc[:off] + text + doc[off + dele:]

        # Text outside [off, off + dele) is the same in doc and new, so
        # widening in doc gives matching word boundaries in both.
        lo, hi = widen(doc, off, off + dele)
        old_words = doc[lo:hi].split()
        new_words = new[lo:hi - dele + len(text)].split()
        sm = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
        written = deleted = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                deleted += i2 - i1
                written += j2 - j1
        # A "{{" the op touches lies within a byte of the change.
        lo = max(0, off - 1)
        notes = new[lo:off + len(text) + 1].count(NOTE) - doc[lo:off + dele + 1].count(NOTE)

        if written or deleted or notes:
            timed = secs is not None and epoch is not None
            events.append(Event(epoch + int(secs) if timed else None, written, deleted,
                                max(0, notes), max(0, -notes), timed))
        doc = new

    source = path.with_name(path.name[1:].removesuffix(".replay"))
    # The log doesn't hold the final newline vim adds when writing.
    if source.exists() and source.read_bytes() not in (doc, doc + b"\n"):
        print(f"  warning: replay of {path.name} doesn't match {source.name}", file=sys.stderr)
    return [e if e.timed else e._replace(when=epoch or 0) for e in events]


def in_period(event, cutoff):
    return event.when >= cutoff if event.timed else cutoff == float("-inf")


def period_start(period):
    """Unix time the period starts at; -inf for "all"."""
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return midnight.timestamp()
    if period == "week":
        return (midnight - timedelta(days=midnight.weekday())).timestamp()
    if period == "month":
        return midnight.replace(day=1).timestamp()
    return float("-inf")


def title(period, events):
    now = datetime.now()
    if period == "day":
        return f"Writing today, {now:%A %-d %B}"
    if period == "week":
        return f"Writing this week, from {datetime.fromtimestamp(period_start('week')):%A %-d %B}"
    if period == "month":
        return f"Writing this month, {now:%B %Y}"
    return f"Writing since {datetime.fromtimestamp(min(e[0] for e in events)):%-d %B %Y}"


# Edits further apart than this are separate sessions; the idle time between
# sessions is cut out of the chart. Under the shortest gap between poms
# (break plus a pause), over the 10 minute break inside one.
SESSION_GAP = W.session_gap_min * 60
SESSION_PAD = W.session_pad_min * 60
TICK_STEPS = [m * 60 for m in (1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720)]


def find_sessions(times):
    """Group sorted unix times into [(first, last)] runs of edits."""
    sessions = []
    for t in times:
        if sessions and t - sessions[-1][1] <= SESSION_GAP:
            sessions[-1][1] = t
        else:
            sessions.append([t, t])
    return [tuple(s) for s in sessions]


def group_sessions(events):
    """Split events (sorted by time) into sessions."""
    sessions = []
    for e in events:
        if sessions and e.when - sessions[-1][-1].when <= SESSION_GAP:
            sessions[-1].append(e)
        else:
            sessions.append([e])
    return sessions


def session_poms(session):
    return max(1, round((session[-1].when - session[0].when) / (CONFIG["POM_MINUTES"] * 60)))


def book_words():
    """Words in the stories as they'll appear in the book."""
    return sum(len(clean(p.read_text(encoding="utf-8")).split())
               for p in RAW_STORIES.glob("*.md"))


def open_notes():
    return sum(p.read_bytes().count(NOTE) for p in RAW_STORIES.glob("*.md"))


def fit_rates(sessions):
    """Minutes per net word and per note resolved; None where unknown."""
    obs = [(session_poms(s) * CONFIG["POM_MINUTES"], sum(e.written - e.deleted for e in s),
            sum(e.resolved for e in s)) for s in sessions]
    tw = sum(t * w for t, w, _ in obs)
    ww = sum(w * w for _, w, _ in obs)
    editing = sum(r >= CONFIG["MIN_NOTES_RESOLVED"] for _, _, r in obs)
    if editing >= CONFIG["MIN_EDIT_SESSIONS"]:
        # Least squares, no intercept: solve the 2x2 normal equations.
        tr = sum(t * r for t, _, r in obs)
        rr = sum(r * r for _, _, r in obs)
        wr = sum(w * r for _, w, r in obs)
        det = ww * rr - wr * wr
        if det:
            a, b = (tw * rr - tr * wr) / det, (tr * ww - tw * wr) / det
            if a > 0 and b > 0:
                return a, b
    a = tw / ww if ww else None
    return (a if a and a > 0 else None), None


def describe(minutes):
    if minutes is None:
        return "unknown"
    poms = minutes / CONFIG["POM_MINUTES"]
    return (f"{minutes / 60:,.0f} h, {poms:,.0f} poms, "
            f"{poms / CONFIG['POMS_PER_DAY']:,.0f} days at {CONFIG['POMS_PER_DAY']} poms a day")


def report_rates(events):
    """Print rates for the period's events."""
    written = sum(e.written for e in events)
    net = written - sum(e.deleted for e in events)
    poms = sum(session_poms(s) for s in group_sessions(sorted(events)))
    hours = poms * CONFIG["POM_MINUTES"] / 60
    print(f"Poms:     {poms} ({hours:.1f} h)")
    if poms:
        print(f"Per pom:  {net / poms:.0f} net, {written / poms:.0f} written")
        print(f"Per hour: {net / hours:.0f} net, {written / hours:.0f} written")


def report_estimate(history):
    """Print time to finish, from every session so far."""
    sessions = group_sessions(sorted(history))
    a, b = fit_rates(sessions)
    net = sum(e.written - e.deleted for e in history)
    added = sum(e.added for e in history)
    target, have, notes = CONFIG["TARGET_WORDCOUNT"], book_words(), open_notes()
    to_go = max(0, target - have)
    future_notes = added / net * to_go if net > 0 else 0

    poms = sum(session_poms(s) for s in sessions)
    print(f"\nBook: {have:,} of {target:,} words, {to_go:,} to go; {notes} open notes")
    print(f"Rates from all {poms} poms so far:")
    print(f"  Per net word: {f'{a * 60:.1f} s' if a else 'unknown'}")
    editing = sum(sum(e.resolved for e in s) >= CONFIG["MIN_NOTES_RESOLVED"] for s in sessions)
    print(f"  Per note:     {f'{b:.1f} min' if b else 'unknown'}"
          + ("" if b else f" (needs {CONFIG['MIN_EDIT_SESSIONS']} sessions resolving {CONFIG['MIN_NOTES_RESOLVED']}+ notes;"
                          f" {editing} so far)"))
    if added and net > 0:
        print(f"  Notes:        1 per {net / added:.0f} net words")

    drafting = a * to_go if a else None
    editing_time = b * (notes + future_notes) if b else None
    total = drafting + editing_time if drafting is not None and editing_time is not None else None
    print("Time to finish:")
    print(f"  Drafting: {describe(drafting)}")
    print(f"  Editing:  {describe(editing_time)} ({notes} open notes + ~{future_notes:,.0f} to come)")
    print(f"  Total:    {describe(total)}")

    # Overall is by time: what's been spent against that plus what's left.
    spent = poms * CONFIG["POM_MINUTES"]
    print("Complete:")
    print(f"  Drafting: {min(have / target, 1):.1%}")
    print(f"  Overall:  {f'{spent / (spent + total):.1%}' if total is not None else 'unknown'}")


def compress(times):
    """Map unix times onto an x axis with the idle gaps between sessions cut out.

    Returns (x_of, sessions, gaps): x_of maps a time inside a session to x,
    sessions is [(start, end)] in real time, gaps is the x of each break.
    """
    sessions = [(a - SESSION_PAD, b + SESSION_PAD) for a, b in find_sessions(times)]
    active = sum(b - a for a, b in sessions)
    # Keep short sessions visible next to long ones.
    widths = [max(b - a, active / 40) for a, b in sessions]
    gap_w = sum(widths) / 20

    starts, gaps, x = [], [], 0
    for w in widths:
        starts.append(x)
        x += w + gap_w
        gaps.append(x - gap_w / 2)

    def x_of(t):
        for (a, b), x0, w in zip(sessions, starts, widths):
            if t <= b:
                return x0 + (t - a) / (b - a) * w
        raise ValueError(t)

    return x_of, sessions, gaps[:-1]


def time_ticks(x_of, sessions):
    """Tick positions and labels: each session's start, plus round times where they fit."""
    active = sum(b - a for a, b in sessions)
    step = next((s for s in TICK_STEPS if s >= active / 8), TICK_STEPS[-1])
    min_dx = (x_of(sessions[-1][1]) - x_of(sessions[0][0])) / 12

    starts = []
    for a, _ in sessions:
        t = a + SESSION_PAD
        if not starts or x_of(t) - x_of(starts[-1]) >= min_dx * 0.6:
            starts.append(t)
    chosen = list(starts)
    for a, b in sessions:
        for t in range(int(a // step + 1) * step, int(b), step):
            if all(abs(x_of(t) - x_of(c)) >= min_dx for c in chosen):
                chosen.append(t)

    ticks, labels, last_day = [], [], None
    for t in sorted(chosen):
        dt = datetime.fromtimestamp(t)
        # Round times are aligned to UTC multiples; fine for whole-hour offsets.
        label = f"{dt:%H:%M}"
        if t in starts and dt.date() != last_day:
            label += f"\n{dt:%-d %b}"
            last_day = dt.date()
        ticks.append(x_of(t))
        labels.append(label)
    return ticks, labels


def running(events, fields, start=0):
    """Running totals of the given Event fields, one point per event."""
    totals = [[start] for _ in fields]
    for e in events:
        for total, field in zip(totals, fields):
            total.append(total[-1] + getattr(e, field))
    return totals


def plot(events, heading, notes_start):
    """Chart running words and notes, and open the image.

    notes_start is the number of open notes when the period began.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    # Green for progress, orange for setbacks. A deeper green would be hard to
    # tell from the orange with red-weak colour vision; this one isn't.
    good, bad = "#1baf7a", "#eb6834"
    if not events:
        print("Nothing to chart.")
        return
    events = sorted(events)
    x_of, sessions, gaps = compress([e.when for e in events])
    xs = [x_of(sessions[0][0])] + [x_of(e.when) for e in events] + [x_of(sessions[-1][1])]

    def totals(*fields):
        # Hold the last value out to the end of the final session.
        return [t + t[-1:] for t in running(events, fields)]

    written, deleted = totals("written", "deleted")
    net = [w - d for w, d in zip(written, deleted)]
    added, resolved = totals("added", "resolved")
    open_ = [notes_start + a - r for a, r in zip(added, resolved)]

    # One chart around a shared time axis: words grow upwards from it and
    # notes downwards, each half on its own scale. Same colours in both
    # halves: green is progress (words written, notes resolved), orange is
    # the opposite (words deleted, notes added), black is the overall figure.
    fig, (words_ax, notes_ax) = plt.subplots(
        2, 1, sharex=True, figsize=(9, 6.5), dpi=150, gridspec_kw={"height_ratios": [3, 2]})
    fig.patch.set_facecolor(surface)
    halves = [
        (words_ax, "Words", [("Written", written, good), ("Deleted", deleted, bad), ("Net", net, ink)]),
        (notes_ax, "Notes", [("Added", added, bad), ("Resolved", resolved, good), ("Open", open_, ink)]),
    ]
    for ax, name, series in halves:
        ax.set_facecolor(surface)
        for label, ys, color in series:
            ax.step(xs, ys, where="post", color=color, linewidth=2, clip_on=False)
            ax.annotate(f"{label} {ys[-1]:,}", (xs[-1], ys[-1]), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=9, color=ink)
        for x in gaps:
            ax.axvline(x, color=grid, linewidth=0.8, linestyle=(0, (3, 3)), zorder=0)
        top = max(max(ys) for _, ys, _ in series) * 1.05 or 1
        ax.set_ylim(0, top)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=muted, labelsize=9, length=0, pad=7)
        ax.set_ylabel(name, color=muted, fontsize=10)
        # Both halves meet at 0; label it once, on the words side.
        ax.yaxis.set_major_formatter(lambda y, _, ax=ax: "" if ax is notes_ax and y == 0 else f"{y:,.0f}")
    notes_ax.invert_yaxis()

    # The shared time axis, with the breaks marked on it. On the notes half,
    # which is drawn last, so the marks sit on top of both halves' lines.
    words_ax.axhline(0, color=muted, linewidth=0.8, zorder=1, clip_on=False)
    for x in gaps:
        notes_ax.text(x, 0, "//", ha="center", va="center", zorder=3, color=muted, fontsize=9,
                      clip_on=False, bbox=dict(facecolor=surface, edgecolor="none", pad=0))

    words_ax.set_title(heading, loc="left", fontsize=12, color=ink, pad=26)
    handles = [matplotlib.lines.Line2D([], [], color=c, linewidth=2) for c in (good, bad, ink)]
    words_ax.legend(handles, ["Written / Resolved", "Deleted / Added", "Net / Open"],
                    loc="lower left", bbox_to_anchor=(0, 1), ncol=3, frameon=False,
                    fontsize=9, labelcolor=ink, borderaxespad=0)
    ticks, labels = time_ticks(x_of, sessions)
    notes_ax.set_xticks(ticks, labels)
    notes_ax.set_xlim(xs[0], xs[-1])
    fig.align_ylabels()
    fig.tight_layout()
    fig.subplots_adjust(hspace=0)

    out = Path(tempfile.gettempdir()) / "words_written.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    print(f"Chart: {out}")
    subprocess.Popen(["xdg-open", str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description="Count words written and deleted, from the replayvim logs.")
    parser.add_argument("--period", choices=["day", "week", "month", "all"], default=W.period)
    parser.add_argument("--plot", action="store_true", help="chart the running totals")
    parser.add_argument("replays", nargs="*", type=Path, metavar="REPLAY")
    args = parser.parse_args()
    paths = args.replays or sorted(RAW_STORIES.glob(".*.replay"))
    cutoff = period_start(args.period)

    history, all_events = [], []
    for path in paths:
        events = count(path)
        history += events
        events = [e for e in events if in_period(e, cutoff)]
        w = sum(e.written for e in events)
        d = sum(e.deleted for e in events)
        if w or d:
            print(f"  {path.name[1:].removesuffix('.replay')}: +{w} -{d}")
        all_events += events
    total_w = sum(e.written for e in all_events)
    total_d = sum(e.deleted for e in all_events)

    print(f"Written: {total_w}")
    print(f"Deleted: {total_d}")
    print(f"Net:     {total_w - total_d:+d}")
    print(f"Notes:   +{sum(e.added for e in all_events)} -{sum(e.resolved for e in all_events)}")
    report_rates(all_events)
    report_estimate(history)
    if args.plot:
        before = [e for e in history if not in_period(e, cutoff)]
        notes_start = sum(e.added - e.resolved for e in before)
        plot(all_events, title(args.period, all_events) if all_events else "", notes_start)


if __name__ == "__main__":
    main()
