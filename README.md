# Travel book

A book of stories from a two-year bike trip, and the pipeline that places every ride, photo and diary entry on the route

## Setup

```
make apt       # system packages (asks for sudo only if some are missing)
make mounts    # where each raw data directory lives on this machine
make secret NAME=deepgram_api_key   # each secret a target needs (see scripts/settings.py)
make osm       # OSM extracts and routing tiles: a few hours, once
make           # mount, clean, index, place everything, count words, build the book
make review    # the review app, at http://localhost:8000
make help      # what the pipeline builds, and the target for each output
```

The review app is where you check and correct what the pipeline worked out: stays, how each
stretch was travelled, unclear places, each diary entry's events, the tags, and each story beside
its days. See `docs/review_app.md`; the files it writes are described in `docs/manual_files.md`.

Raw data kept outside the repo is mounted read-only in the hidden `.mounts/`, and each mount point under `raw/` is a symlink to it, so the mounts stay out of the file manager's sidebar. `make unmount` removes the symlinks too.

Settings are managed with [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/): the defaults are in `settings.yaml`, and `scripts/settings.py` declares each one's type. Override one for a run with `SETTINGS_<NAME>=<value> make <target>`.

Secrets are read from the system keyring: `make secret NAME=<name>` stores one (it prompts for the value). Where there's no keyring (SSH, cron, containers), put it in `~/.secrets/<name>` instead, with `chmod 600`.

`make clean` removes what's quick to rebuild; `make purge` removes all generated output. Neither touches `manual/`, your answers, which is in git. See `CLAUDE.md` for the layout and conventions.
