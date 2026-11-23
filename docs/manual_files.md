# Your files: manual/

Everything you decide lives in `manual/`, tracked in git. The review app writes these as you work
(`docs/review_app.md`); you can also edit them by hand, with the app closed or reloaded after. Each
row of stays.csv, travel_modes.csv, known_places.csv and dismissed.csv has an `id`: leave it alone, and leave it empty on a row you add by hand (the app fills it
in on the next change to that file). Earlier versions are in `manual/.history/` (not in git).

| File | Columns | Used by |
|------|---------|---------|
| `stays.csv` | `id, first_night, leaving, town, plus_code, notes, checked, found`. Local dates, `YYYY-MM-DD`; `leaving` is the morning you left. `plus_code` a full plus code. `notes` are yours; `checked` the day you confirmed it; `found` what make stays found when it was added | make route (you're there every night), the Stays and Story views |
| `travel_modes.csv` | `id, start, end, mode, note`. **UTC**, `YYYY-MM-DD` (a whole day) or `YYYY-MM-DDTHH:MM`; an empty `end` is the start's day or minute. `mode` one of `modes` in settings.yaml | make route, make check |
| `known_places.csv` | `id, start_date, end_date, time, town, country, note, lat, lon`. Local dates; `time` local `HH:MM:SS`, or UTC with a `Z`. A town where a name is shared can name its region: `Strandfontein (Western Cape)`. With its own `lat, lon` the town isn't looked up | make places, route, locate |
| `place_picks.csv` | `town, country, geonameid, name, lat, lon`: which place a shared town name meant (a GeoNames id, or a point of your own) | make places |
| `dismissed.csv` | `id, check, start_utc, end_utc, lat, lon, note`: findings that are fine. One covers a finding of the same check within about 100 m over an overlapping span. `check` `found_stay` is a found stay that isn't one | make check, the Stays view |
| `ignored_photos.csv` | `file, note`: photos whose GPS is wrong, by path or name | make route |
| `events/KIND/STEM.json` | an entry's events as you reviewed them: `{file, kind, language, verified, note, saved, events: [{title, summary, date, place, people, tags, quote, date_guessed}]}` | make events (used as saved, never re-asked) |
| `tags.csv` | `tag, description`: the tags events can carry, `lower_case_names` | make events, the Diary and Tags views |
| `glossary.txt` | names, one per line (`#` comments): spelled right in transcripts and events | make transcripts, make events |
| `pilot.txt` | recording file names (as in clean/diary/audio) to compare the speech-to-text providers on | make transcripts-pilot |

How known places and stays are used, in more detail:

- A GPS point within `locate.gps_hours` of an entry wins over any known place.
- Otherwise a timed known place within `locate.pass_hours`, then one covering the day. On a day two
  rows share, mornings take the first row and later the second.
- A known place of several days is reached at `route.stay_arrive` on the first and left at
  `route.stay_leave` on the last; with its own lat, lon it's there every night in between, as a stay is.
- A known place of your own replaces a photo or looked-up place within `route.replace_min` of it,
  which is how the app moves one.
