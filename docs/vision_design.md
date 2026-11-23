# Software Design Description
## For Travel book — Vision

Version 1.0  
Prepared by the author, with Claude  
Personal project  
2026-11-23

## Table of Contents
<!-- TOC -->
* [1. Introduction](#1-introduction)
  * [1.1 Document Purpose](#11-document-purpose)
  * [1.2 Subject Scope](#12-subject-scope)
  * [1.3 Definitions, Acronyms, and Abbreviations](#13-definitions-acronyms-and-abbreviations)
  * [1.4 References](#14-references)
  * [1.5 Document Overview](#15-document-overview)
* [2. Design Overview](#2-design-overview)
  * [2.1 Stakeholder Concerns](#21-stakeholder-concerns)
  * [2.2 Selected Viewpoints](#22-selected-viewpoints)
* [3. Design Views](#3-design-views)
* [4. Decisions](#4-decisions)
* [5. Appendixes](#5-appendixes)
<!-- TOC -->

## Revision History

| Name | Date | Reason For Changes | Version |
|------|------|--------------------|---------|
| Claude | 2026-11-23 | First version: the refactor of ../travel_book (phase v1) | 1.0 |

## 1. Introduction

### 1.1 Document Purpose

How the travel book project is built, for the author and for whoever changes it: its parts, the
data each reads and writes, and the decisions behind them (§4), so that a change can be checked
against them. The requirements it meets are in `vision_requirements.md`.

### 1.2 Subject Scope

The whole project: the pipeline (scripts/, the Makefile), the files it reads and writes (raw/,
clean/, manual/, processing/) and the review app (scripts/review/).

### 1.3 Definitions, Acronyms, and Abbreviations

As in the SRS §1.3. Also: **step**, a script a make target runs; **plugin**, a cleaner in
scripts/cleaners/ or an indexer in scripts/index/; **view**, one screen of the review app.

### 1.4 References

`vision_requirements.md` (normative), `CONTRIBUTING.md` (normative), `CLAUDE.md` (the conventions),
the Makefile's header (the outputs), `docs/*.md` (how to use the review app and the manual files).

### 1.5 Document Overview

§2 names who cares about what and the viewpoints used; §3 gives the views: the data flow, the
layout of files, the steps, the review app; §4 the decisions, D-001 onwards.

## 2. Design Overview

### 2.1 Stakeholder Concerns

The author as user: an accurate record, review that's quick and clear, nothing lost (undo,
history, git), no repeated paid work. The author as maintainer: one obvious place for each thing,
settings in one file, outputs reproducible, steps that can be rerun.

### 2.2 Selected Viewpoints

#### 2.2.1 Context

The author, the raw data's directories (mounted read-only), the web services named in SRS §2.1.
View 001.

#### 2.2.2 Composition

Steps and plugins, shared helpers, the review app's server, API modules and views. Views 002, 004.

#### 2.2.3 Logical

The data flow from raw to the outputs. View 001.

#### 2.2.4 Physical

The directory layout. View 002.

#### 2.2.5 Structure

Not used beyond View 002.

#### 2.2.6 Dependency

Which step reads which output: the Makefile's rules, summarised in View 001.

#### 2.2.7 Information

The manual files' columns and the findings' fields. View 003.

#### 2.2.8 Interface

The review app's HTTP API. View 004.

#### 2.2.9 Interaction

A change from the app to manual/ and back. View 005.

#### 2.2.10 Algorithm

The location algorithms (stays, route, checks, locate) are unchanged from the old project and
described in each script's docstring.

#### 2.2.11 State Dynamics

An item's status in the review app. View 005.

#### 2.2.12 Concurrency

The server is threaded; changes to manual/ go through one lock; rebuilds run one at a time.

#### 2.2.13 Patterns

Atomic writes; plugins picked up by file name; mtime-cached reads.

#### 2.2.14 Deployment

One machine; the Whisper worker copied to an ssh host.

#### 2.2.15 Resources

The OSM data and Valhalla tiles (about 25 GB), the compressed audio (1.5 GB), Whisper's model (3 GB).

## 3. Design Views

- ID: 001-data-flow
- Title: From raw data to the review app and the book
- Viewpoint: Logical, Dependency
- Representation:
  ```
  raw/ (read-only mounts, stories in git)
    -> clean/ (build_clean.py + scripts/cleaners/)            make clean-data
    -> processing/index/ (build_index.py + scripts/index/)    make index
       -> track/ (track.py)                                   make track
       -> places/ (places.py, manual/known_places.csv, place_picks.csv)   make places
       -> stays/found.json (stays.py)                         make stays
       -> route/ (route.py: track, places, photos, manual/stays.csv, travel_modes.csv, OSM)  make route
       -> route/findings.json (checks.py, manual/dismissed.csv)            make check
       -> located/ (locate.py)                                make locate
       -> audio/, asr/ (transcribe.py)                        make audio, transcripts
       -> events/ (events.py, manual/tags.csv, manual/events/)            make events
  Komoot (fetch.py) -> the raw data's own directories                    make fetch-komoot, fetch-meta
  clean/stories -> story_plans/*.csv Words (counts.py)                   make counts
  review app (scripts/review/): reads processing/, writes manual/        make review
  clean/stories -> processing/story_tex -> book.pdf                      make book
  ```
- More Information: Implements R-FUNC-DATA-001 to 004, R-FUNC-LOC-001 to 006, R-FUNC-DIARY-001 to 003, R-FUNC-BOOK-001 to 003, R-MAINT-002, R-REL-002, R-REL-003 (build_clean refuses while a mount is down), R-COST-001 (the paid outputs are in KEEP). The Makefile header lists every output. Decisions D-002, D-003, D-013, D-014.

- ID: 002-layout
- Title: Where everything is
- Viewpoint: Physical, Composition
- Representation: raw/ (only read here; the Komoot downloads write to the directories it's mounted from, outside the repo, as SRS C-1 allows), clean/ (built), manual/ (the author's answers, in git, history in manual/.history), processing/ (built; KEEP spares the slow and paid parts), scripts/ (one script per step; common/ helpers; cleaners/ and index/ plugins; review/ the app), settings.yaml (every tunable), story_plans/, notes/, book.tex.
- More Information: Paths are constants in scripts/repo.py (D-004). Implements R-MAINT-001, R-FUNC-DATA-003, R-INT-001, R-SEC-001, R-REL-001. Decisions D-004, D-011, D-012, D-015 (secrets).

- ID: 003-manual-files
- Title: The author's answers
- Viewpoint: Information
- Representation: stays.csv (id, first_night, leaving, town, plus_code, notes, checked, found); travel_modes.csv (id, start, end, mode, note; UTC); known_places.csv (id, start_date, end_date, time, town, country, note, lat, lon; local, or UTC with Z); place_picks.csv; dismissed.csv (id, check, start_utc, end_utc, lat, lon, note); ignored_photos.csv (file, note); tags.csv (tag, description); events/KIND/STEM.json; glossary.txt (names for transcription and events); pilot.txt (recordings to compare the providers on, make transcripts-pilot). Findings (processing/route/findings.json) carry id, check, title, span, place, facts (fields), rows (ids), fix (what the app offers), dismissed.
- More Information: Implements R-FUNC-DATA-003, R-FUNC-DIARY-003, R-FUNC-LOC-005, R-UI-003. Decisions D-005, D-006, D-007. docs/manual_files.md describes each.

- ID: 004-review-api
- Title: The review app's server and views
- Viewpoint: Interface, Composition
- Representation: scripts/review/server.py serves static/ and /api/: settings, status, rebuild, rows/TABLE, change, undo, changes, offsets, pluscode, thumb, files; and each view's data from api/route.py, stays.py, places.py, diary.py (with tags), story.py. store.py applies changes; status.py says what's stale and runs make. The page: static/app.js (frame, banner, toasts, dialogs), lib.js (API, formatting, Queue, Facts, MapView, keys), views/*.js. Preact and htm, Leaflet and marked are vendored in static/vendor/.
- More Information: Implements R-UI-001 to 004, R-FUNC-REV-001 to 010, R-PERF-001, R-SEC-001. Decisions D-008, D-009, D-010, D-016.

- ID: 005-change-cycle
- Title: A change, from the app to the file and back
- Viewpoint: Interaction, State Dynamics
- Representation: The inspector's action sends POST /api/change {why, ops}; store.py applies the ops in memory, checks each row, refuses a stale base with 409, saves each file (the old version to manual/.history) and logs the change; the page reloads its data. Undo restores the files of the last change. An item's status (the page shows them as to do, labelled, fine and wait for rebuild): todo → labelled (a row covers it) or dismissed (the author said fine) or pending (a row it's about changed since make check); the banner offers the rebuild that settles pending ones.
- More Information: Implements R-FUNC-REV-001 to 003. Decision D-009.

## 4. Decisions

- ID: D-001
- Title: Refactor into the cookiecutter layout, keeping the outputs
- Context: ../travel_book had 33 scripts, config spread over the Makefile, config.toml and constants, and four review pages each grown feature by feature.
- Options: Clean up in place; start from the template and port.
- Outcome: Start from my-cookiecutter and port each step, checking its outputs against the old ones, because the template's conventions answer most of the mess and the old outputs are the test.
- More Information: Meets R-MAINT-003.


- ID: D-002
- Title: One-to-one cleaners: an overnight recording becomes several tracks in one file
- Context: The old clean_gpx.py split a ride left recording overnight into _a, _b files; the template's cleaners write one file per raw file.
- Options: Extend build_clean for many outputs; put each ride in its own <trk> of one file.
- Outcome: One file with a <trk> per ride, because every raw file had one <trk>, so each <trk> is a ride and the outputs stay identical.
- More Information: Meets R-FUNC-DATA-001, R-MAINT-003.


- ID: D-003
- Title: Indexers record per-file facts; locate places them
- Context: The old build_index placed and dated files with the track, offsets, places and route, and read the transcripts, so it had to be deleted and rebuilt around them.
- Options: One index step as before; per-file indexers plus a locate step.
- Outcome: Indexers record what a file says about itself; make locate joins them with the rest, which ends the index → transcripts → index cycle.
- More Information: Meets R-FUNC-DATA-002, R-FUNC-LOC-006.


- ID: D-004
- Title: Paths are layout, not settings
- Context: The template puts tunables in settings.yaml.
- Options: Paths as settings; paths as constants in repo.py.
- Outcome: Constants in repo.py: moving a directory is a code change, while settings are what you'd tune. The Makefile holds no config: OSM regions, port, provider and backend are settings.
- More Information: Meets R-INT-001.


- ID: D-005
- Title: Travel modes as one table in settings
- Context: Each mode's router, colour and speed limit were in three scripts.
- Options: Keep them in the scripts; one table in settings.
- Outcome: settings.modes: router, max_kmh, colour, vehicle per mode.
- More Information: Meets R-INT-001, R-FUNC-LOC-004, R-FUNC-LOC-005.


- ID: D-006
- Title: Every manual row has an id
- Context: The old pages found rows by matching five to eight text fields.
- Options: Keep matching on the fields; give each row an id.
- Outcome: An id column in stays, travel_modes, known_places and dismissed; route.csv names each anchor's row; findings name their rows by id.
- More Information: Meets R-FUNC-REV-002, R-FUNC-REV-005.


- ID: D-007
- Title: Machine evidence never in the author's notes
- Context: The stays map pre-filled a stay's notes with its evidence ("4n: ride 2, bridged 2").
- Options: Keep it in the notes; compute and show it, keeping the old text apart.
- Outcome: Evidence is computed and shown as a table; the migration moved the old text to a found column.
- More Information: Meets R-FUNC-REV-004, R-UI-003.


- ID: D-008
- Title: One review app, no data in pages, no offline mode
- Context: Four pages, data baked in at build time, an offline file:// mode with copy/download/load and localStorage.
- Outcome: One server-backed app; it reads processing/ live, says when an output is stale, and rebuilds it with make.
- More Information: Meets R-UI-001, R-FUNC-REV-003, R-FUNC-REV-010.


- ID: D-009
- Title: Row-level changes with undo
- Context: The old pages saved whole files (or appended lines), with history but no undo.
- Outcome: POST /api/change with operations on rows by id, a base to refuse stale edits, one log entry per change for Undo (D-006).
- More Information: Meets R-FUNC-REV-001, R-FUNC-REV-002.


- ID: D-010
- Title: Preact and htm, vendored
- Context: The pages were hand-written DOM code in Python strings.
- Options: Plain JS modules; Preact with htm; a framework with a build step.
- Outcome: Preact with htm, vendored, no build step: components and state for about 15 KB.
- More Information: Meets R-UI-001, R-MAINT-001.


- ID: D-011
- Title: Whitespace in raw names becomes _ in clean/
- Context: The template refuses to run on whitespace and asks for the originals to be renamed; 480 recordings and photos have spaces, known by name to other apps.
- Outcome: build_clean maps them to _ in clean/; caches were renamed to match. Flagged for the template.
- More Information: Meets R-FUNC-DATA-001.


- ID: D-012
- Title: Cleaners in scripts/cleaners/
- Context: The template's .claude/settings.json denies Edit(clean/**), which also matches scripts/clean/.
- Outcome: The cleaners live in scripts/cleaners/; flagged for the template.
- More Information: Meets R-MAINT-001.


- ID: D-013
- Title: Compressed audio is a processing step
- Context: Compression is per file, so could be a cleaner, but the indexer needs the WAV's header and the remote worker the .ogg.
- Outcome: clean/diary/audio links the originals; make audio compresses into processing/audio.
- More Information: Meets R-FUNC-DIARY-001, R-FUNC-DATA-002.


- ID: D-014
- Title: The events prompt kept word for word
- Context: Answers are stale when the prompt's hash changes, and redoing them costs subscription time.
- Outcome: The prompt, tag list format and glossary (comment lines included) are as before; the hash is unchanged, so every cached answer still counts.
- More Information: Meets R-COST-001, R-FUNC-DIARY-002.


- ID: D-015
- Title: Secrets from the keyring, then ~/.secrets
- Context: The old scripts read ~/.secrets/claude, ~/.secrets/komoot (two lines) and ~/.<provider>-api-key.
- Outcome: As the template reads them: one field per secret (komoot_email, komoot_password, anthropic_api_key, deepgram_api_key, openai_api_key, elevenlabs_api_key).
- More Information: Meets R-SEC-001.


- ID: D-016
- Title: Unclear known places are settled in the review app, not the terminal
- Context: known_places.py asked about each ambiguous town at the terminal, copying a geojson.io link to the clipboard.
- Options: Keep the prompts; write the questions out and answer them on a map in the review app.
- Outcome: places.py writes processing/places/questions.json; the Places view shows the options beside the GPS points around and saves the pick to manual/place_picks.csv, so make places never waits for input.
- More Information: Meets R-FUNC-LOC-002, R-FUNC-REV-006.


- ID: D-017
- Title: legs.csv keeps the rows' note and the flags apart
- Context: The old legs.csv had one notes column mixing the travel mode row's note with what looked wrong ("fast for a bike").
- Options: Keep one column; split it into mode_note and flags.
- Outcome: Split, so the review app shows the note as yours and the flags as findings (vision R-UI-003). Joined, they equal the old column.
- More Information: Meets R-MAINT-003, R-FUNC-LOC-004.

- ID: D-018
- Title: CSVs end their lines with LF
- Context: The old scripts wrote CSVs with Python's default CRLF.
- Options: Keep CRLF; write LF, as the template's scripts do.
- Outcome: LF everywhere (common/tables.py); the content is otherwise identical.
- More Information: Meets R-MAINT-003, R-FUNC-LOC-004.

## 5. Appendixes

### Appendix A: the old scripts and what replaced them

| Old | New |
|-----|-----|
| clean_gpx.py, clean_story.py | scripts/cleaners/gpx.py, stories.py |
| build_track.py | track.py |
| known_places.py (interactive) | places.py + the Places view |
| find_stays.py, stays_map.py | stays.py + the Stays view |
| build_route.py | route.py |
| check_route.py, find_crossings.py, suggest_modes.py | checks.py |
| build_index.py | scripts/index/*.py + locate.py |
| compress_audio.py, transcribe_diary.py, detect_languages.py, whisper_server.sh | transcribe.py |
| transcribe_providers.py | common/asr.py |
| extract_events.py, llm.py | events.py, common/llm.py |
| download_komoot.sh, komoot_gpx.py, komoot_meta.py | fetch.py |
| bike_osm.py + the Makefile's OSM rules | osm.py |
| words_written.py, update_word_counts.py | progress.py, counts.py |
| track_lookup.py, diary_dates.py | common/*.py, index/audio.py |
| serve_review.py, review_map.py, review_diary.py, story_dashboard.py(.html) | scripts/review/ |
| find_gaps.py, gap_files.py, view_photos.sh, read_diary.sh | the Places view's Gaps |
| undo_to_replay.py | dropped: a one-off, done |
