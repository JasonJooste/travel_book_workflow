# The review app

`make review` starts it and opens http://localhost:8000 (`review.port` in settings.yaml). It only
listens on this machine. Ctrl+C in its terminal stops it; running `make review` again while it's
up just opens the page.

Every view has the same three parts: the **list** of things to look at on the left (with tabs to
filter it and a search box), the **map** (or the entry, or the story) in the middle, and the
**inspector** on the right, which shows what's selected: its facts as fields, the rows of yours it's
about, and what you can do about it. The highlighted action is the usual one, and Enter does it.

| Key | |
|-----|---|
| `j` / `k` | next / previous in the list |
| `Enter` | the highlighted action (`Ctrl+Enter` while typing in a field) |
| `u` | undo the last change |
| `/` | search the list |
| `Esc` | cancel a selection, or leave a field |
| `?` | the keys and views |

**Saving.** Every change saves at once to `manual/` (a toast says what, with Undo). **History**
lists your recent changes; **Undo** puts back the files the last one touched. Every earlier version
is also kept in `manual/.history/`, and `manual/` is in git. If a row changed since the page loaded
it (in your editor, or another tab), the change is refused and the page reloads it, rather than
overwriting it.

**Rebuilding.** When what a view shows was built before your latest changes (the route after you
label a stretch, say), a yellow banner says so, with **Rebuild**: it runs the make target, shows its
output, and reloads the view when it's done.

Times are local, with the UTC offset; hover over one for UTC.

## Stays

Your stays (`manual/stays.csv`, which `make route` uses) beside the ones `make stays` found from
rides and photos. **To check** holds the stays that differ from the one found over the same
nights (other dates, or more than `stays.radius_km` away) and found stays that aren't in yours.

The inspector compares yours and the found one field by field, the differences in amber; lets you
edit the town, dates, plus code and notes (saved as you leave each field); and lists each night as
found: what placed it (a ride, a photo, any fix, or nothing), and how far that is from your pin.
On the map: the track of those days (arriving purple, during blue, leaving pink), the photos, each
night's candidate places (the one chosen bigger), the found place's ring, and your pin. Drag the
pin, click a night's dot, or search for a place, to move the stay.

**Confirm** (Enter) marks a stay checked. A found stay not in yours: **Add to your stays**, or
**Not a stay**. **Use the found dates** / **place** copy them over.

## Route

How each stretch was travelled, and what looks wrong. The list holds:

- **findings** of `make check`: rivers crossed with no bridge (a boat?), suggested modes (a Komoot hike,
  a bus), legs too fast for their mode, out-and-back spikes to a photo, long days, detours, rows that
  label nothing or overlap, short runs of a vehicle, known places not on the route;
- every **gap leg** (a stretch with no recording, routed or drawn straight) and run of **hops**
  (short steps between photos and known places).

Status: **to do**; **labelled** (a travel mode row now covers it); **fine** (you dismissed it);
**wait for rebuild** (a row it's about changed since `make check`).

The inspector shows the facts (distance, time, speed against the mode's limit, from and to), the
rows it's about (delete one, or keep one of two), the other rows on that stretch, and the fix it
suggests: **label** the span with a mode (number keys pick it; the span is editable), **move** a
point onto the route, **remove** known places, or **Looks fine**, which dismisses it into
`manual/dismissed.csv`.

On the map, click the route twice to select any stretch and label it. Zoomed in, the photos, known
places and stays the route goes through show as dots: click one to see it, and drag its handle to
move it (saved as a known place of yours at its time). **Rows** lists every travel mode row, to
find and edit.

## Places

- **To settle**: a known place whose town matched several places, or none. The options are on the
  map beside where you were before and after; pick one (number keys), click the map, or search.
  Saved to `manual/place_picks.csv`; rebuild to use it.
- **Gaps** and **Filled**: days with no ride, photo with GPS or stay, with their photos and diary
  entries (or those of ±1 or ±2 days around them), and where you were last and next seen as grey
  dots on the map. Click the map where you were (Enter saves it), or name the town, to add a known
  place; its From and To dates (yyyy-mm-dd, ‹ › to step a day) start as the days still open. Once
  every day has a known place the gap moves to Filled, where it lists what you said, on the map too.
- **Known places**: every row of `manual/known_places.csv`, to edit or delete.

## Diary

Each entry's events, as Claude gave them (`make events`). The recording plays in the middle with
its transcript following along (click a piece to jump there); the events' quotes are highlighted.
On the right, edit the events: title, summary, date (and whether it's a guess), place, people,
tags (Claude's suggested tags show dashed: click one to add it to the tag list and the event), and
the quote (**Find** shows it in the text). Add, reorder and delete events; note anything about the
entry. Everything saves as you go to `manual/events/`; `make events` then uses your version and never
sends the entry to Claude again. **Mark verified** (Ctrl+Enter) when it's right; **Back to Claude's
events** drops your version.

## Tags

The tag list (`manual/tags.csv`) with how many events carry each: edit a description in place, add
or delete a tag (not one still on events you reviewed). On the right: the tags Claude suggests,
**Ask Claude which tags overlap**, and the tags most often found together.

## Story

A story beside everything from its days (its Start time and Stop time in `story_plans/*.csv`,
widened by "days either side"): the story itself (read-only; it follows your edits within seconds,
notes highlighted), the route on a map, a table day by day with the ride's profile and stats, the
photos, the events, the diary entries, and **Suggestions**: ask Claude to compare the story with
the sources for inconsistencies, details to add and answers to your notes. Click a photo, an entry or
a day to see it on the right.
