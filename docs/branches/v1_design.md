# Software Design Description
## For Travel book — Phase v1: the refactor

Version 1.0  
Prepared by the author, with Claude  
Personal project  
2026-11-24

**Status: in progress**, as `v1_requirements.md` says.

## Table of Contents
<!-- TOC -->
* [1. Introduction](#1-introduction)
* [2. Design Overview](#2-design-overview)
* [3. Design Views](#3-design-views)
* [4. Decisions](#4-decisions)
* [5. Appendixes](#5-appendixes)
<!-- TOC -->

## Revision History

| Name | Date | Reason For Changes | Version |
|------|------|--------------------|---------|
| Claude | 2026-11-24 | First version | 1.0 |

## 1. Introduction

### 1.1 Document Purpose

The detail of phase v1's design that the vision SDD leaves to the phase: the migration, the
review app's API and files, and the decisions taken while building it.

### 1.2 Subject Scope

Phase v1 (`v1_requirements.md`).

### 1.3 Definitions, Acronyms, and Abbreviations

As in the vision documents.

### 1.4 References

The vision SRS and SDD; `v1_requirements.md`.

### 1.5 Document Overview

§3 the views; §4 the decisions taken in this phase.

## 2. Design Overview

### 2.1 Stakeholder Concerns

As the vision §2.1; for this phase, above all that nothing the old project knew is lost.

### 2.2 Selected Viewpoints

Information (the migration's mapping), Interface (the API's routes), Composition (the front end's files).

## 3. Design Views

- ID: 101-migration
- Title: From the old project to the new
- Viewpoint: Information
- Representation: A one-off script (kept outside the repo) copied raw/stories (hidden replay and undo files included), story_plans, notes (without tag_index.csv), book.tex, .nvimrc and mounts.toml; processing/manual/* into manual/, each row of stays, travel_modes, known_places and route_ok given a random 8-hex id (vision D-006), route_ok.csv as dismissed.csv (an exact duplicate dropped), notes/tag_index.csv as tags.csv, known_places/picks.csv as place_picks.csv, diary/vocab/glossary.txt and diary/pilot.txt into manual/, manual/.history/<name>-<stamp> as .history/<name>/<stamp>. In stays.csv, the parts of notes matching the found summary's patterns (`Nn: ...`, `MM-DD at ...`, `Nn at <code>`, `from the town row in known_places`, `point: ...`) moved to the new found column. It hard-linked the OSM data, GeoNames and Whisper's models, and the compressed audio (as processing/audio), rewrote valhalla.json for the new paths, and copied the transcripts (asr/whisper; the old processing/transcripts as asr/local) and Claude's answers, renaming every file and `file`/`source` field with whitespace as clean/ names it.
- More Information: Implements R-FUNC-MIG-101. Vision D-006, D-007, D-011.

- ID: 102-api
- Title: The review app's routes
- Viewpoint: Interface
- Representation: `server.py`'s docstring lists them. Changes: `POST /api/change {"why": text, "ops": [{"table", "op": "add"|"update"|"delete", "id" or "key", "base", "row"}, {"entry": [kind, stem], "op": "put"|"drop", "record"}]}`; the reply `{"id", "results"}`; errors `{"error", "current"?}` with 400, 404 or 409. Undo: `POST /api/undo`. Rebuilds: `POST /api/rebuild {"target"}`, one of the targets in status.py; `GET /api/rebuild?since=N`. Each view's data is from its module in api/; the Route view's items come with `status`, `when` (`{start, end}`, each `{utc, local, offset}`), `t` (minutes since 1970), `facts`, `rows`, `fix`.
- More Information: Implements R-FUNC-REV-001 to 003, R-UI-101. Vision View 004.

- ID: 103-front-end
- Title: The page's files
- Viewpoint: Composition
- Representation: static/index.html loads Leaflet and app.js. app.js: the views along the top, the stale banner and Rebuild, toasts with Undo, dialogs, History. lib.js: `api`, `change` (with the 409 dialog), `undo`, `useData` (reloads on every change and rebuild), formatting (`fmtDay`, `fmtKm`, `fmtMinutes`, `fmtOffset`), `Queue`, `Facts` (labels and units for each fact), `MapView` (one set of tiles everywhere), `useLayer`, `useKeys` (the inner part wins a key), `PlaceSearch` (Photon), `Action`. views/*.js: one per view.
- More Information: Implements R-UI-001 to 004, R-UI-102. Vision D-010.

## 4. Decisions

- ID: D-101
- Title: The phase documents' vision changes are made on v1
- Context: The vision documents were written after the code, and their first commit's check failed while a pipeline run was using the working tree.
- Options: Write them on main and merge main into v1; write them on v1 and let the merge into main bring them.
- Outcome: On v1, as CONTRIBUTING allows when the phase shows the vision: switching branches mid-run would have run main's files.

- ID: D-102
- Title: Statuses computed by the server, live
- Context: The old route page worked out on the page which items rows covered, repeating make route's rule in JavaScript.
- Options: Keep it in the page; compute it in the API from the rows now, with route.covers().
- Outcome: In the API: one implementation, and the page shows the same status make route would.
- More Information: Meets R-FUNC-REV-101 and the vision's R-FUNC-REV-005.

- ID: D-103
- Title: Findings remember the rows they were made with
- Context: After a row changes, a finding about it may be settled or not, and only make check can say.
- Outcome: checks.py writes findings_built_with.json (the travel mode rows and known places it saw); a finding a changed row overlaps is "wait for rebuild".
- More Information: Meets R-FUNC-REV-101 and the vision's R-FUNC-REV-003 and R-FUNC-REV-005.

## 5. Appendixes

None.
