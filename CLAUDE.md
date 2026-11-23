# Travel book

A book of stories from a two-year bike trip, and the pipeline that places every ride, photo and diary entry on the route.
It was refactored from `../travel_book` (kept as an archive): `docs/vision_design.md` Appendix A maps the old scripts to the new.

## Layout
- `raw/`: source data, only ever read. Small files are tracked in git; the rest are bind-mounted read-only from outside the repo (`scripts/mounts.py`): each mount point is a symlink to the mount in `.mounts/`. Never write, move or delete anything in it.
- `clean/`: built by `make clean-data`, never edited by hand. It mirrors `raw/`: a file claimed by a cleaner in `scripts/cleaners/` is rewritten, everything else is a symlink back to `raw/`, and whitespace in names becomes `_`. `clean/.sources.csv` maps each file to its raw source.
- `manual/`: the user's answers, tracked in git: stays, travel modes, known places, place picks, dismissed findings, ignored photos, reviewed diary entries (`events/`), the tag list, the glossary. Written by hand or by the review app (through `scripts/review/store.py`, which keeps every old version in `manual/.history/` for Undo). Each row of stays, travel_modes, known_places and dismissed has an `id`. No make target removes it.
- `processing/`: every other generated output, one directory per step. `processing/index/` holds what each file in `clean/` says about itself; `processing/located/` when and where each was made.
- `scripts/`: one script per step, each run by a make target. Docstring first, with a `Usage:` line. Helpers shared by several live once, in `scripts/common/` (geo, times, tables, track, towns, photos, llm, asr). Paths are constants in `scripts/repo.py`.
- `scripts/cleaners/`, `scripts/index/`: cleaners and indexers, picked up by file name (see the docstrings of `build_clean.py` and `build_index.py`). The cleaners aren't in `scripts/clean/`, as the template has them, because `.claude/settings.json` denies `Edit(clean/**)`, which also matches that directory.
- `scripts/review/`: the review app (`make review`): `server.py`, the API modules in `api/`, the store and status, and the page in `static/` (Preact and htm, Leaflet, marked: vendored in `static/vendor/`, no build step).
- `settings.yaml`: the default settings, read by `scripts/settings.py` (see Conventions).
- `docs/`: the vision SRS and SDD (`vision_requirements.md`, `vision_design.md`), one requirements and design pair per phase in `docs/branches/` (`<phase>_requirements.md`, `<phase>_design.md`), the vendored templates in `docs/des_req_templates/`, and how to use the files the user edits by hand: input formats, review tools.

## Requirements, design and branches
`CONTRIBUTING.md` is the standard workflow, shared by every project made from the template: follow it. In short: branches are `main` → `<phase>` → `<phase>-<feature>`, and plans nest two levels: the vision on `main`, and one requirements and design pair per phase, written before the code, that cites the vision by ID, only adds detail, and also tracks the phase's progress (status line), what was decided against (design decisions) and how it's verified (SRS §4). Feature branches are implementation only: no documents of their own, but what they settle goes into the phase documents in the same branch. The vision, the phase documents and the code never contradict each other (fix one before merging); requirement and decision IDs are never reused. Don't edit the standard sections of `CONTRIBUTING.md`; project-specific rules go in its last section. Git hooks have an LLM check the documents on commit and merge (`scripts/git-hooks/`): when one fails, fix what it reports, and never skip the check (`--no-verify`) or change the hooks setup; whether to skip is the user's call.

## Conventions
- The Makefile is the entry point. Every output has a target, and the header comment lists each output, what it's made from and its target: keep it current.
- Read from `clean/`, never from `raw/` directly; only cleaners read `raw/`.
- A fix to raw data is a cleaner, not an edit to the raw file. `clean/` is for cheap per-file fixes; anything slow or that combines files belongs in `processing/`.
- Things that are slow or costly to regenerate (downloads, paid APIs, hours of compute) and files holding the user's answers go in `KEEP`, so `make clean` spares them. `make purge` removes everything.
- Write each output under a temporary name and rename it, so an interrupted run leaves nothing half-written. Long steps skip what's already done, so they can simply be rerun.
- Pin Python packages in `requirements.txt` and list system packages in `apt-requirements.txt`, each with a comment saying which target needs it.
- Settings are managed with pydantic-settings in `scripts/settings.py`: each one is a typed field there, and its default is in `settings.yaml`, with a comment saying what it's for. Scripts read them with `from settings import settings`, never with their own constants, `argparse` defaults, `os.environ` or config files. To add one, add the field and its default in the same commit. `SETTINGS_<NAME>=<value>` overrides one for a run.
- Secrets never go on a command line (visible in `ps`), in the repo or in `settings.yaml`. Each one is a `SecretStr | None = None` field in `scripts/settings.py`, which reads it from the system keyring (service `secrets`, the field name as the username), or from `~/.secrets/<field>` where there's no keyring. The user stores one with `make secret NAME=<field>`; never read, print or log a secret's value yourself, and don't try to get around the deny rules that block it.
- Hidden files are ignored throughout.
- No whitespace in file or directory names outside `raw/`: make can't handle it. In `raw/` there are hundreds, which `make clean-data` maps to `_` in `clean/` (vision SDD D-011); `scripts/rename_spaces.py` can still rename them at the source, but that renames the original data, so the user runs it, never Claude.
- The review app changes `manual/` only through `store.change()`: operations on rows by id, checked, with a base to refuse stale edits. Show values as labelled fields, never inside a generated sentence; times in local time with UTC on hover.
- The outputs of the location steps, `events.csv` and the transcripts are checked against `../travel_book/processing`: a change that alters them needs a recorded decision.
