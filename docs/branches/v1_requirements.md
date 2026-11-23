# Software Requirements Specification
## For Travel book — Phase v1: the refactor

Version 1.0  
Prepared by the author, with Claude  
Personal project  
2026-11-24

**Status: in progress.** Done: the pipeline (clean, index, track, places, stays, route, check, locate,
transcription, events, progress, counts, downloads, osm), the settings, the review app's server and
all six views, the vision documents. Remaining: `make book` and the downloads run for real (they
need the TeX packages, the Komoot secrets and disk space); a proper `make venv` (the current .venv
borrows the old project's packages, for want of disk).

## Table of Contents
<!-- TOC -->
* [1. Introduction](#1-introduction)
* [2. Product Overview](#2-product-overview)
* [3. Requirements](#3-requirements)
* [4. Verification](#4-verification)
* [5. Appendixes](#5-appendixes)
<!-- TOC -->

## Revision History

| Name | Date | Reason For Changes | Version |
|------|------|--------------------|---------|
| Claude | 2026-11-24 | First version, with the phase's results | 1.0 |

## 1. Introduction

### 1.1 Document Purpose

What phase v1 delivers: the vision's v1 requirements (vision SRS §2.6), with the detail the vision
leaves out, and how each was verified. It doesn't repeat the vision: it cites it by ID.

### 1.2 Product Scope

Phase v1 refactors `../travel_book` into the my-cookiecutter layout (vision SDD D-001): every v1
requirement, keeping the old outputs (R-MAINT-003). R-FUNC-BOOK-004 is left to a later phase.

### 1.3 Definitions, Acronyms, and Abbreviations

As in the vision SRS §1.3. **Old**: `../travel_book` at its last commit, with its processing/ as it was.

### 1.4 References

The vision SRS and SDD; `v1_design.md`; `../travel_book`.

### 1.5 Document Overview

§3 adds detail to the vision's v1 requirements; §4 records how each was checked and what it showed.

## 2. Product Overview

### 2.1 Product Perspective

As the vision §2.1. Phase v1 migrates the old project's inputs, answers and slow or paid outputs
into the new layout once (v1 design, View 101); the old project stays untouched.

### 2.2 Product Functions

The vision's §2.2, all of it; R-FUNC-BOOK-004 (photos and maps in the book) waits for a later phase.

### 2.3 Product Constraints

The vision's C-1 to C-5. Also, for this phase: the migration never writes to the old project.

### 2.4 User Characteristics

As the vision §2.4.

### 2.5 Assumptions and Dependencies

The old project's processing/ outputs are the reference for R-MAINT-003.

### 2.6 Apportioning of Requirements

Every requirement below is in v1.

## 3. Requirements

### 3.1 External Interfaces

- ID: R-UI-101
- Title: The views and their order (details R-UI-001)
- Statement: The views shall be Stays, Route, Places, Diary, Tags, Story, in that order along the top; the URL shall be `#/<view>/<item>`.
- Verification Method: Demonstration

- ID: R-UI-102
- Title: Number keys pick (details R-UI-002)
- Statement: Where an item offers a choice of modes or places, the number keys 1 to 9 shall pick one.
- Verification Method: Demonstration

### 3.2 Functional

- ID: R-FUNC-MIG-101
- Title: Migration (details R-FUNC-DATA-003, R-COST-001)
- Statement: The one-off migration shall bring the stories (with their replay logs), story plans, notes, book.tex, mounts.toml, every manual file (each row of stays, travel_modes, known_places and dismissed given an id, as vision D-006 says), the tag list, the glossary and pilot list, the place picks, the reviewed entries, the transcripts, Claude's answers, the OSM data, GeoNames and the compressed audio into the new layout, renaming files whose names had whitespace as clean/ does, and moving the auto-generated text in the stays' notes into their found column.
- Acceptance Criteria: Nothing paid for is redone: the transcription and events dry runs report what the old ones did.
- Verification Method: Test

- ID: R-FUNC-LOC-101
- Title: Identical location outputs (details R-MAINT-003, R-FUNC-LOC-001 to 004, 006)
- Statement: The track, the places, the found stays, the route (route.csv, legs.csv, stats.csv, unlabelled.csv) and the located files shall equal the old ones, apart from line endings (vision D-018), the clean/ file names (vision D-011), route.csv's new ref column (vision D-006) and legs.csv's notes split into mode_note and flags (vision D-017).
- Verification Method: Test

- ID: R-FUNC-LOC-102
- Title: The same findings (details R-FUNC-LOC-005)
- Statement: make check shall find what the old check_route, find_crossings and suggest_modes found, with the old dismissals carried over.
- Verification Method: Test

- ID: R-FUNC-DIARY-101
- Title: The same events (details R-FUNC-DIARY-002, D-014)
- Statement: events.csv shall equal the old index/events.csv apart from file names, and the prompt's hash shall be the old one.
- Verification Method: Test

- ID: R-FUNC-REV-101
- Title: Statuses (details R-FUNC-REV-004 to 006)
- Statement: Route items shall show as to do, labelled, fine or wait for rebuild (the vision's todo, labelled, dismissed, pending); stays differs, matches, confirmed, yours only, not in yours or not a stay; places to settle or answered.
- Verification Method: Demonstration

### 3.3 Quality of Service

- ID: R-PERF-101
- Title: Warm requests (details R-PERF-001)
- Statement: The heaviest request, the Route view's items, shall answer within a second once warm.
- Verification Method: Test

### 3.4 Compliance

None.

### 3.5 Design and Implementation

As the vision §3.5.

### 3.6 AI/ML

As the vision §3.6: no prompt changes in v1 (D-014).

## 4. Verification

| Requirement ID | Method | How | Status | Evidence |
|----------------|--------|-----|--------|----------|
| R-FUNC-MIG-101 | test | the migration script's report; transcribe and events dry runs | Passed | 116 stays, 823 travel mode rows, 150 known places, 34 dismissals (a duplicate dropped), 10 reviewed entries, 527 Whisper transcripts, 92 answers; events dry run 1681 entries, 10 reviewed, 30 done, 52 stale, as the old |
| R-FUNC-LOC-101 | test | diff against the old processing/ | Passed | track identical (bar CRLF); places 150 rows, 0 differences; stays 71, 0 differences; route 100,558 points, 0 differences; legs 580, 0; stats and unlabelled identical; located photos 5291, audio 1329, written 206, blog 188, 0 differences each |
| R-FUNC-LOC-102 | test | counts against the old outputs | Passed | 0 open checks (the old checks.csv was empty), 58 crossings, 12 suggestions; 28 findings dismissed (the 34 dismissals also cover findings that no longer occur) |
| R-FUNC-DIARY-101 | test | events.py --limit 0, diff | Passed | 364 events, 0 differences; hash 467aedd6b63b |
| R-INT-001 (vision) | test | load the settings; add a key settings.py lacks | Passed | a bad key or type stops every script at start |
| R-FUNC-DATA-001, 002 (vision) | test | make clean-data and make index on the mounted raw data | Passed | 328 cleaned, 7385 linked; 7713 files indexed, 9 not covered by an indexer |
| R-REL-002 (vision) | test | a second run of transcribe, events and osm | Passed | 0 to do in each |
| R-FUNC-BOOK-003 (vision) | test | progress.py --period all against words_written.py | Passed | the same figures |
| R-FUNC-REV-001, 002 (vision) | test | /api/change, /api/undo | Passed | add, update with a stale base (409), invalid mode (400), delete, undo twice: the file back byte for byte; a diary entry saved and undone |
| R-FUNC-REV-003 (vision) | demonstration | Rebuild ran make places from the app | Passed | |
| R-UI-101, 102, R-FUNC-REV-101, R-FUNC-REV-004 to 009 (vision) | demonstration | each view in a browser | Passed | screenshots of each view |
| R-UI-003, 004 (vision) | inspection | each view's inspector | Passed | facts as labelled fields; local times with the offset, UTC on hover |
| R-FUNC-DATA-004 (vision) | demonstration | make fetch-komoot, fetch-meta | WIP | needs the Komoot secrets |
| R-PERF-101 | test | timed requests | Passed | route items 0.35 s warm (18 s cold, looking up time zones) |
| R-FUNC-BOOK-001 (vision) | test | make book | WIP | needs the TeX packages and disk space |

## 5. Appendixes

None.
