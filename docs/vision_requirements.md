# Software Requirements Specification
## For Travel book — Vision

Version 1.0  
Prepared by the author, with Claude  
Personal project  
2026-11-23

## Table of Contents
<!-- TOC -->
* [1. Introduction](#1-introduction)
    * [1.1 Document Purpose](#11-document-purpose)
    * [1.2 Product Scope](#12-product-scope)
    * [1.3 Definitions, Acronyms, and Abbreviations](#13-definitions-acronyms-and-abbreviations)
    * [1.4 References](#14-references)
    * [1.5 Document Overview](#15-document-overview)
* [2. Product Overview](#2-product-overview)
    * [2.1 Product Perspective](#21-product-perspective)
    * [2.2 Product Functions](#22-product-functions)
    * [2.3 Product Constraints](#23-product-constraints)
    * [2.4 User Characteristics](#24-user-characteristics)
    * [2.5 Assumptions and Dependencies](#25-assumptions-and-dependencies)
    * [2.6 Apportioning of Requirements](#26-apportioning-of-requirements)
* [3. Requirements](#3-requirements)
    * [3.1 External Interfaces](#31-external-interfaces)
    * [3.2 Functional](#32-functional)
    * [3.3 Quality of Service](#33-quality-of-service)
    * [3.4 Compliance](#34-compliance)
    * [3.5 Design and Implementation](#35-design-and-implementation)
    * [3.6 AI/ML](#36-aiml)
* [4. Verification](#4-verification)
* [5. Appendixes](#5-appendixes)
<!-- TOC -->

## Revision History

| Name | Date | Reason For Changes | Version |
|------|------|--------------------|---------|
| Claude | 2026-11-23 | First version: the refactor of ../travel_book into this template (phase v1) | 1.0 |

## 1. Introduction

This SRS says what the travel book project must do: turn the raw record of a two-year bicycle
trip (rides, photos, a spoken and written diary, blog posts) into a placed, dated, indexed trip
that the author can check and correct, and from which the book's stories are written and built.
It covers every phase; §2.6 says which phase each requirement belongs to. How it's built is in
the vision SDD (`vision_design.md`).

### 1.1 Document Purpose

It is for the author, the only user, and for whoever (Claude included) changes the code: a change
is right when it keeps these requirements, and the verification in §4 says how to tell. It states
what the system does, not how; the SDD holds the how and the decisions behind it.

### 1.2 Product Scope

The product is a Makefile pipeline with Python scripts, plus a local web app for review. It
places every ride, photo and diary entry in time and space; builds the whole route, gaps
included, with how each stretch was travelled; indexes the diary into tagged events; and builds
the book from the stories. Out of scope: publishing, editing the stories (the author's editor
does that), and anything run anywhere but the author's machine (bar the optional remote
transcription worker).

### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Definition |
|------|------------|
| Anchor | A fixed point the route is drawn through: a recorded point, a photo with GPS, a known place, a stay's night. |
| Entry | One diary item: a recording, a written diary file, a blog post or a Komoot description. |
| Event | One thing that happened, as found in an entry: title, summary, date, place, people, tags, quote. |
| Finding | Something make check says looks wrong in the route, or could be labelled. |
| Gap leg | A stretch between two anchors further apart than route.gap_km, with no recording: routed or drawn straight. |
| Known place | A row of manual/known_places.csv: where the author was when no GPS says. |
| Manual file | A file in manual/: the author's answers, written by hand or by the review app. |
| Stay | Several nights in one place: a row of manual/stays.csv. |
| Travel mode row | A row of manual/travel_modes.csv: how a span of time was travelled. |
| SRS / SDD | Software requirements specification / design description. |

### 1.4 References

| Reference | Kind |
|-----------|------|
| `CONTRIBUTING.md`: the requirements, design and branch workflow | normative |
| `vision_design.md`: the vision SDD | normative |
| `docs/*.md`: how to use the files edited by hand and the review app | informative |
| `../travel_book`: the project this one was refactored from, kept as an archive | informative |

### 1.5 Document Overview

§2 gives the context, the constraints and which phase each requirement is in; §3 the
requirements, by area; §4 how each is verified. IDs follow CONTRIBUTING.md (`R-<AREA>-NNN`,
`R-FUNC-<GROUP>-NNN`) and are never reused.

## 2. Product Overview

### 2.1 Product Perspective

It replaces `../travel_book`, which grew a script per feature until its review pages and
configuration were hard to use (see the vision SDD, D-001). It is made from the `my-cookiecutter`
template and keeps its conventions: raw/ → clean/ → processing/, a Makefile entry point,
pydantic-settings. External services it uses: GeoNames and Geofabrik downloads, Valhalla (local),
Komoot's API, speech-to-text providers, Claude (`claude -p` or the API), map tiles and Photon place
search in the browser.

### 2.2 Product Functions

- Clean the raw data into clean/, and index what each file says about itself.
- Build the track from the rides, and the stays from rides and photos.
- Look up the known places, and ask the author where a name is unclear.
- Build the whole route, gaps routed, each stretch with its travel mode; check it for what looks wrong.
- Place and date every photo, recording, written entry and blog post.
- Transcribe the recordings; split every entry into tagged events with Claude.
- Let the author review and correct all of it in one local app, saving to manual/ with undo.
- Build the book from the stories, count their words, and track writing progress; later, with the stories' photos and maps.

### 2.3 Product Constraints

- C-1: Raw data must only ever be read, except by the download scripts (Komoot), which write to its source directories.
- C-2: Everything runs on the author's Linux machine; the review app listens on localhost only.
- C-3: Secrets must never be on a command line or in the repo.
- C-4: Paid calls (speech to text, the Claude API) must never repeat work already paid for.
- C-5: The template's conventions (CLAUDE.md) must hold, or a deviation must be a recorded decision.

### 2.4 User Characteristics

One user: the author, a programmer, who works in a terminal and a browser, often for hours of
review at a time, with the keyboard. Accuracy of the record matters more than speed.

### 2.5 Assumptions and Dependencies

- The raw data stays where mounts.toml says, readable. If not, make refuses rather than losing clean/ files.
- GeoNames, Geofabrik, Komoot and the providers keep their formats; if one changes, its step fails loudly.
- The disk has room for the OSM data (about 25 GB) and the audio.

### 2.6 Apportioning of Requirements

| Requirement | Phase |
|-------------|-------|
| R-FUNC-DATA-001 to 004 | v1 |
| R-FUNC-LOC-001 to 006 | v1 |
| R-FUNC-DIARY-001 to 003 | v1 |
| R-FUNC-REV-001 to 010 | v1 |
| R-FUNC-BOOK-001 to 003 | v1 |
| R-FUNC-BOOK-004 (photos and maps in the book) | Vision |
| R-UI-001 to 004, R-INT-001, R-PERF-001 | v1 |
| R-SEC-001, R-REL-001 to 003, R-MAINT-001 to 003, R-COST-001 | v1 |

## 3. Requirements

### 3.1 External Interfaces

#### 3.1.1 User Interfaces

- ID: R-UI-001
- Title: One review app, one layout
- Statement: The review app shall present every kind of review (stays, route, places, diary, tags, story) in one page with the same layout: a list of items to look at, a map or the entry in the middle, and an inspector showing the selected item.
- Rationale: The old pages each had their own layout, keys and save model.
- Acceptance Criteria: Each view has the three panes; the same keys work in each (R-UI-002).
- Verification Method: Demonstration

- ID: R-UI-002
- Title: The same keys everywhere
- Statement: j/k shall step through the list, Enter take the highlighted action (Ctrl+Enter while typing), u undo the last change, / search the list, Esc cancel, ? show the keys, in every view.
- Rationale: Hours of review by keyboard.
- Acceptance Criteria: Each key does its job in each view.
- Verification Method: Demonstration

- ID: R-UI-003
- Title: Facts as fields
- Statement: The app shall show the numbers and names behind an item (distance, time, speed, the limit, places, modes) as labelled fields with units, never inside a sentence.
- Rationale: The old pages packed findings into text blobs.
- Acceptance Criteria: No finding, stay or entry is described by a generated sentence alone.
- Verification Method: Inspection

- ID: R-UI-004
- Title: Local time, UTC on hover
- Statement: Times shall be shown in the local time of where the author was, with the UTC offset, and the UTC time on hover.
- Rationale: The files keep UTC or local times as suits each; the author thinks in local time.
- Verification Method: Inspection

#### 3.1.2 Hardware Interfaces

None.

#### 3.1.3 Software Interfaces

- ID: R-INT-001
- Title: Settings in one place
- Statement: Every tunable value (thresholds, dates, models, regions, ports) shall be a typed field in scripts/settings.py with its default in settings.yaml, overridable for one run with SETTINGS_<NAME>.
- Rationale: The old project kept config in the Makefile, config.toml and constants in a dozen scripts.
- Acceptance Criteria: No script has its own tunable constant; a bad key or type in settings.yaml fails at start.
- Verification Method: Inspection, Test

### 3.2 Functional

- ID: R-FUNC-DATA-001
- Title: Clean data
- Statement: make clean-data shall build clean/ from raw/: rides split where left recording overnight, stories without front matter or {{notes}}, photo sidecars left out, everything else linked; names with whitespace given _ instead.
- Verification Method: Test

- ID: R-FUNC-DATA-002
- Title: Index
- Statement: make index shall record what each clean file says about itself (EXIF times and GPS, recording times and lengths, dates in names, rides), reusing rows of unchanged files.
- Verification Method: Test

- ID: R-FUNC-DATA-003
- Title: Answers in manual/
- Statement: The author's answers shall live in manual/, tracked in git; no make target shall remove them.
- Verification Method: Inspection

- ID: R-FUNC-DATA-004
- Title: Downloads
- Statement: make fetch-komoot and fetch-meta shall download the recorded Komoot tours, their sports, times and descriptions into the raw data's directories, skipping what's unchanged.
- Verification Method: Demonstration

- ID: R-FUNC-LOC-001
- Title: Track
- Statement: make track shall merge the rides into one track of at most one point a minute within the trip, with the phone's UTC offset at each ride's start.
- Verification Method: Test (identical to the old output)

- ID: R-FUNC-LOC-002
- Title: Known places
- Statement: make places shall look up each known place in GeoNames; where a town matches several places or none, it shall leave the question for the review app rather than ask in the terminal.
- Verification Method: Test

- ID: R-FUNC-LOC-003
- Title: Stays found
- Statement: make stays shall find the stays of two or more nights from rides and photos, each with its evidence night by night.
- Verification Method: Test (identical stays to the old find_stays.py)

- ID: R-FUNC-LOC-004
- Title: Route
- Statement: make route shall build the whole trip as one route through every anchor, routing gaps along OSM roads by their travel mode, with each point naming the row it came from.
- Verification Method: Test (the old route, but for the differences recorded in D-006, D-017, D-018)

- ID: R-FUNC-LOC-005
- Title: Checks
- Statement: make check shall list what looks wrong in the route, river crossings with no bridge and suggested modes, as findings with their facts as fields, leaving out those the author dismissed.
- Verification Method: Test

- ID: R-FUNC-LOC-006
- Title: Locate
- Statement: make locate shall give every photo, recording, written entry and blog post a UTC time, a local date and a place, best source first.
- Verification Method: Test (identical to the old index)

- ID: R-FUNC-DIARY-001
- Title: Transcripts
- Statement: make transcripts shall transcribe each recording once with the chosen provider, with nearby towns and the glossary as vocabulary; and the remote worker shall do the same on another machine.
- Verification Method: Test (dry run), Demonstration

- ID: R-FUNC-DIARY-002
- Title: Events
- Statement: make events shall ask Claude once per entry for its tagged events, keep the answer, and use the author's reviewed version of an entry in place of Claude's.
- Verification Method: Test

- ID: R-FUNC-DIARY-003
- Title: Tags
- Statement: The tag list shall be manual/tags.csv; a tag on events the author reviewed can't be removed from it.
- Verification Method: Test

- ID: R-FUNC-REV-001
- Title: Saves are immediate and undoable
- Statement: Every change in the review app shall save to manual/ at once, keep the version it replaced, and be undoable as one step.
- Verification Method: Test

- ID: R-FUNC-REV-002
- Title: Conflicts are refused
- Statement: A change to a row that changed since the app loaded it shall be refused, saying so, rather than overwrite it.
- Verification Method: Test

- ID: R-FUNC-REV-003
- Title: Stale outputs are shown and rebuilt
- Statement: When an output shown was built before the author's latest answers, the app shall say so and offer to rebuild it, showing the rebuild's progress.
- Verification Method: Demonstration

- ID: R-FUNC-REV-004
- Title: Stays review
- Statement: The app shall show each stay beside the one found over its nights, its differences, its evidence night by night, and let the author confirm, correct, add, remove or dismiss stays.
- Verification Method: Demonstration

- ID: R-FUNC-REV-005
- Title: Route review
- Statement: The app shall list findings, gap legs and hops with their status, and let the author label a span with a travel mode, delete or keep rows, move points onto the route, and dismiss findings; and select any stretch on the map to label it.
- Verification Method: Demonstration

- ID: R-FUNC-REV-006
- Title: Places review
- Statement: The app shall show each unsettled known place with its options on a map, the days with nothing to place the author, and every known place, and let the author pick, add, edit and delete them.
- Verification Method: Demonstration

- ID: R-FUNC-REV-007
- Title: Diary review
- Statement: The app shall play an entry's audio with its transcript following along, its quotes highlighted, and let the author edit, add, reorder and delete its events, and mark it verified.
- Verification Method: Demonstration

- ID: R-FUNC-REV-008
- Title: Tags review
- Statement: The app shall show every tag with its use, the tags Claude suggests, and which tags overlap, and let the author add, describe and delete tags.
- Verification Method: Demonstration

- ID: R-FUNC-REV-009
- Title: Story dashboard
- Statement: The app shall show a story, read-only and following edits, beside the route, days, photos, events and entries of its days, and Claude's suggestions from comparing them.
- Verification Method: Demonstration

- ID: R-FUNC-REV-010
- Title: No hidden state
- Statement: Where the author is in a view shall be in the URL, not in browser storage; the app shall have no offline mode.
- Verification Method: Inspection

- ID: R-FUNC-BOOK-001
- Title: Book
- Statement: make book shall build book.pdf from book.tex and the cleaned stories.
- Verification Method: Test

- ID: R-FUNC-BOOK-002
- Title: Word counts
- Statement: make counts shall write each story's words into its row of story_plans/*.csv.
- Verification Method: Test

- ID: R-FUNC-BOOK-003
- Title: Progress
- Statement: make progress shall replay the stories' edit logs into words written and deleted, notes added and resolved, and the time to finish.
- Verification Method: Test (identical figures to the old words_written.py)

- ID: R-FUNC-BOOK-004
- Title: Photos and maps in the book
- Statement: The book should be able to place a story's photos and a map of its route.
- Verification Method: Demonstration

### 3.3 Quality of Service

#### 3.3.1 Performance

- ID: R-PERF-001
- Title: Responsive review
- Statement: Once warm, each review app request should answer within a second; the first may take longer while it reads the outputs.
- Verification Method: Test

#### 3.3.2 Security

- ID: R-SEC-001
- Title: Secrets and exposure
- Statement: Secrets shall come from the system keyring or ~/.secrets, never the command line or the repo; the review app shall listen on 127.0.0.1 only and serve only clean/, processing/audio and its own files.
- Verification Method: Inspection

#### 3.3.3 Reliability

- ID: R-REL-001
- Title: No half-written outputs
- Statement: Every output shall be written under a temporary name and renamed into place.
- Verification Method: Inspection

- ID: R-REL-002
- Title: Resumable long steps
- Statement: Transcription, events and OSM shall skip what's done, so an interrupted run can simply be rerun.
- Verification Method: Test

- ID: R-REL-003
- Title: Nothing lost to a mount being down
- Statement: make clean-data shall refuse to run while a mount is down.
- Verification Method: Inspection

#### 3.3.4 Availability

Not applicable: run on demand on one machine.

#### 3.3.5 Observability

Each step prints what it did and counts; the review app prints each change it saves.

### 3.4 Compliance

None beyond the map tiles' and Photon's usage terms (attribution, light use).

### 3.5 Design and Implementation

#### 3.5.1 Installation

make apt, make venv, make mounts, then make secret NAME=<name> for each secret a target needs.

#### 3.5.2 Build and Delivery

Python packages pinned in requirements.txt; system packages in apt-requirements.txt.

#### 3.5.3 Distribution

One machine; the optional Whisper worker on an ssh host.

#### 3.5.4 Maintainability

- ID: R-MAINT-001
- Title: One script per step
- Statement: Each make target shall run one script, each with a docstring and Usage line; helpers shared by scripts shall live once, in scripts/common/.
- Verification Method: Inspection

- ID: R-MAINT-002
- Title: The Makefile header is the map
- Statement: The Makefile's header comment shall list every output, what it's made from and its target.
- Verification Method: Inspection

- ID: R-MAINT-003
- Title: Behaviour kept in the refactor
- Statement: The refactor shall keep the old outputs, changed only where a recorded decision says so.
- Verification Method: Test (§4)

#### 3.5.5 Reusability

The review app's store, status and shared parts are project-specific; nothing is meant for reuse.

#### 3.5.6 Portability

Linux only (bindfs, the apt packages).

#### 3.5.7 Cost

- ID: R-COST-001
- Title: Paid work done once
- Statement: A transcript or Claude answer once paid for shall be kept (processing/ in KEEP) and reused; a dry run shall say the cost of a paid run before it starts.
- Verification Method: Test

#### 3.5.8 Deadline

None.

#### 3.5.9 Proof of Concept

None.

#### 3.5.10 Change Management

Per CONTRIBUTING.md: a branch per phase, its documents updated with the code.

### 3.6 AI/ML

#### 3.6.1 Model Specification

Claude splits entries into events (events.py) and checks stories against sources (the Story view); Whisper or a provider transcribes. Models are settings (events.*, transcribe.*).

#### 3.6.2 Data Management

The author's own diary only. Transcripts and answers are kept in processing/asr and processing/events; the prompt's hash marks answers made with an older prompt, tag list or glossary as stale.

#### 3.6.3 Guardrails

Answers are checked against a JSON schema; tags not in the list or proposed are refused; dates are validated.

#### 3.6.4 Ethics

Personal data stays local, sent only to the chosen provider or Claude.

#### 3.6.5 Human-in-the-Loop

Every event can be reviewed and corrected in the Diary view; a reviewed entry is never sent again.

#### 3.6.6 Model Lifecycle and Operations

A model or prompt change makes answers stale; make events ARGS=--redo-stale redoes them.

## 4. Verification

| Requirement ID | Verification Method | Test/Artifact Link | Status | Evidence |
|----------------|---------------------|--------------------|--------|----------|
| R-UI-001, 002 | demonstration | each view in a browser | Passed | docs/branches/v1_requirements.md §4 |
| R-UI-003, 004 | inspection | each view's inspector | Passed | v1 §4 |
| R-INT-001 | test | settings load; a bad key or type fails | Passed | v1 §4 |
| R-FUNC-DATA-001, 002 | test | make clean-data, make index; the located outputs match the old index | Passed | v1 §4 |
| R-FUNC-DATA-003 | inspection | manual/ in git; clean and purge don't touch it (Makefile) | Passed | |
| R-FUNC-DATA-004 | demonstration | make fetch-komoot, fetch-meta | WIP | needs the Komoot secrets |
| R-FUNC-LOC-001, 003, 004, 006 | test | diff against ../travel_book/processing | Passed | v1 §4: identical but for the differences D-006, D-011, D-017 and D-018 record |
| R-FUNC-LOC-002 | test | make places against the old places.csv | Passed | v1 §4: identical, no questions |
| R-FUNC-LOC-005 | test | findings counts against the old checks, crossings and suggestions | Passed | v1 §4 |
| R-FUNC-DIARY-001 | test | transcribe.py run --dry-run sees the migrated transcripts | Passed | v1 §4 |
| R-FUNC-DIARY-002 | test | events.py --dry-run and --limit 0 against the old | Passed | v1 §4: same counts and hash, identical events.csv |
| R-FUNC-DIARY-003 | test | /api/change refuses removing a tag on reviewed events | Passed | store.py |
| R-FUNC-REV-001, 002 | test | /api/change and /api/undo round trip | Passed | v1 §4 |
| R-FUNC-REV-003 | demonstration | the banner, and Rebuild running make places | Passed | v1 §4 |
| R-FUNC-REV-004 to 009 | demonstration | each view in a browser | Passed | v1 §4 |
| R-FUNC-REV-010 | inspection | static/: the URL holds the view and item; localStorage holds only the map's tiles, which isn't where you are | Passed | |
| R-FUNC-BOOK-001 | test | make book | WIP | needs the TeX packages and disk space |
| R-FUNC-BOOK-002 | test | make counts | Passed | |
| R-FUNC-BOOK-003 | test | progress.py --period all against words_written.py | Passed | v1 §4 |
| R-FUNC-BOOK-004 | demonstration | | Not started | Vision |
| R-PERF-001 | test | request times against the warm server | Passed | v1 §4 |
| R-SEC-001 | inspection | settings.py, server.py (127.0.0.1, served paths) | Passed | |
| R-REL-001 | inspection | common/tables.py write_text; each step writes through it | Passed | |
| R-REL-002 | test | rerunning transcribe, events, osm does nothing new | Passed | v1 §4 |
| R-REL-003 | inspection | build_clean.py checks the mounts | Passed | |
| R-MAINT-001 to 003 | inspection, test | scripts/, the Makefile header, v1 §4 | Passed | |
| R-COST-001 | test | dry runs print the cost; caches in KEEP | Passed | |

## 5. Appendixes

The old scripts and what replaced them are listed in the vision SDD, Appendix A.
