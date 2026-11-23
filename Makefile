# Travel book: a book of stories from a two-year bike trip, and the pipeline that places every
# ride, photo and diary entry on the route.
#
#   raw/...                    source data, only ever read: the stories tracked in git, the diary,
#                              blog posts, photos and GPX mounted read-only from outside the repo
#     -> clean/...             the same tree, ready to use: rides split where left recording
#                              overnight, stories without front matter or {{notes}}, photo sidecars
#                              left out, the rest symlinks to raw/, names without whitespace
#                                                                               (make clean-data)
#     -> processing/index/     every file in clean/, and what each says about itself: EXIF times
#                              and GPS, recording times and lengths, dates in names, rides  (make index)
#
#   The location pipeline (make all of it with make locate):
#     index/rides                          -> processing/track/: points.csv, offsets.csv (UTC
#                                             offsets), coverage.txt, track.png       (make track)
#     Geofabrik extracts (osm.regions)     -> processing/osm/: trip.osm.pbf, waterways, Valhalla
#                                             routing tiles; hours, once                (make osm)
#     manual/known_places.csv + GeoNames   -> processing/places/: places.csv, questions.json for
#                                             the Places view; picks in manual/place_picks.csv
#                                                                                    (make places)
#     rides + photo GPS                    -> processing/stays/found.json: the stays of several
#                                             nights, for the Stays view                (make stays)
#     track, places, photos, manual/stays.csv, manual/travel_modes.csv
#                                          -> processing/route/: route.csv, legs.csv, route.gpx,
#                                             route.geojson, stats.csv, route.png       (make route)
#     route, track, OSM, Komoot tours      -> processing/route/findings.json: what looks wrong,
#                                             and what could be labelled; manual/dismissed.csv
#                                             holds the ones that are fine              (make check)
#     index + track + places + route       -> processing/located/: photos, audio, written, blog:
#                                             when and where each was made             (make locate)
#
#   The diary:
#     clean/diary/audio -> processing/audio/<stem>.ogg, small, for upload           (make audio)
#       -> processing/asr/<provider>/: transcripts, with nearby towns and manual/glossary.txt as
#          vocabulary (make transcripts; a paid service, or transcribe.provider whisper: free,
#          slow). make transcripts-pilot compares the providers on manual/pilot.txt. On another
#          machine: make transcripts-remote ACTION=push|start|status|fetch|stop|remove
#     transcripts, written diary, blog posts, Komoot descriptions
#       -> processing/events/: what happened in each, by Claude, tagged from manual/tags.csv;
#          events.csv and suggested_tags.csv. Reviewed entries are in manual/events/  (make events)
#
#   The review app, at http://localhost:8000 (review.port):                         (make review)
#     Stays, Route, Places, Diary, Tags and Story views over everything above, each saving what
#     you decide to manual/ as you go. make review STORY=<name> opens a story's dashboard.
#
#   The book:
#     clean/stories/<name>.md -> processing/story_tex/<name>.tex -> book.pdf          (make book)
#     the Words column of story_plans/*.csv, from clean/stories                     (make counts)
#     raw/stories/.<name>.md.replay -> words written and time to finish     (make progress, with
#                                      PERIOD=day|week|month|all and a chart)
#
#   Downloads into the raw data's own directories (the only writes to raw data):
#     make fetch-komoot: recorded Komoot tours as GPX; make fetch-meta: their sports, times and
#     descriptions. The login is the secrets komoot_email and komoot_password.
#
#   Raw data kept outside the repo is bind-mounted read-only at the paths in
#   mounts.toml (make mounts to set up, make mount / unmount): each raw/ mount
#   point is a symlink to the mount in the hidden .mounts/, which keeps it out
#   of the file manager's sidebar. The config and mount points are local to
#   this machine and never committed.
#   Every make run first mounts any that aren't mounted yet.
#
#   Settings: defaults in settings.yaml, typed and loaded by scripts/settings.py
#   (pydantic-settings). SETTINGS_<NAME>=<value> make ... overrides one for a run,
#   nested ones with __: SETTINGS_TRANSCRIBE__PROVIDER=whisper make transcripts.
#   Secrets are read from the system keyring (make secret NAME=<name> to store one),
#   or from ~/.secrets/<name> where there's no keyring.
#
#   make hooks turns on the git hooks that check the SRS and SDD (see CONTRIBUTING.md).
#
#   Your answers are in manual/, tracked in git: no make target removes them.
#   make clean removes what's quick to rebuild. make purge removes everything in
#   clean/ and processing/, including the slow outputs listed in KEEP.
#
# Hidden files are ignored throughout. Whitespace in raw/ names becomes _ in clean/.

# Mount any raw data that isn't mounted yet, before anything looks for it.
# A failure doesn't stop make, so targets that don't need it still build.
ifeq ($(filter help hooks mounts mount unmount mount-status apt secret,$(MAKECMDGOALS)),)
$(shell python3 scripts/mounts.py mount >&2)
endif

# Python tools come from .venv, rebuilt whenever requirements.txt changes
VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: all help hooks venv apt mounts mount unmount mount-status secret clean-data index clean purge \
  track osm places stays route check locate audio transcripts transcripts-pilot transcripts-remote \
  languages events review book counts progress fetch-komoot fetch-meta geonames
.DELETE_ON_ERROR:

all: locate counts book

# The comment at the top of this file
help:
	@sed -n '/^#/!q; s/^# \{0,1\}//p' Makefile

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements.txt
	@touch $@

# System packages from apt-requirements.txt; only asks for sudo if some are missing
APT_PACKAGES := $(shell sed 's/\#.*//' apt-requirements.txt)

apt:
	@missing=$$(for p in $(APT_PACKAGES); do \
	  dpkg-query -W -f='$${Status}' $$p 2>/dev/null | grep -q 'ok installed' || echo $$p; done); \
	if [ -n "$$missing" ]; then \
	  echo "Installing missing system packages from apt-requirements.txt (needs sudo):"; \
	  for p in $$missing; do grep "^$$p\b" apt-requirements.txt | sed 's/^/  /'; done; \
	  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q $$missing; fi

# The doc checks in scripts/git-hooks/ (CONTRIBUTING.md). Git config isn't cloned, so run this in
# every clone. No fast-forward merges: they skip the merge hook. Pulls still fast-forward.
hooks:
	git config core.hooksPath scripts/git-hooks
	git config merge.ff false
	git config pull.ff true

# Asks where each mount comes from; writes mounts.toml
mounts:
	@python3 scripts/mounts.py configure

mount: apt
	@python3 scripts/mounts.py mount

unmount:
	@python3 scripts/mounts.py unmount

mount-status:
	@python3 scripts/mounts.py status

# Store a secret in the system keyring, where scripts/settings.py finds it. It prompts for the
# value, so it never goes on a command line.
secret: | $(VENV)/.installed
	@test -n "$(NAME)" || { echo 'Usage: make secret NAME=<settings field>'; exit 1; }
	@$(PY) -m keyring set secrets $(NAME)

# Always run: the script itself skips what's up to date
clean-data: | $(VENV)/.installed
	@$(PY) scripts/build_clean.py

# Always run after clean-data: rows for unchanged files are reused
index: clean-data
	@$(PY) scripts/build_index.py processing/index

# Each step below is a script that reads the settings, so each runs when its script, its inputs
# or settings.yaml change. COMMON is what they share
COMMON := $(wildcard scripts/common/*.py) scripts/settings.py scripts/repo.py settings.yaml
INDEXED = $(wildcard processing/index/*.csv)

track: processing/track/points.csv

processing/track/points.csv: $(INDEXED) scripts/track.py $(COMMON) | index
	$(PY) scripts/track.py

# Extracts download once; delete one in processing/osm/extracts to refresh it
osm: | $(VENV)/.installed
	$(PY) scripts/osm.py

geonames: processing/geonames/cities500.txt

processing/geonames/cities500.txt:
	@mkdir -p $(@D)
	curl -fsSL -o $(@D)/cities500.zip https://download.geonames.org/export/dump/cities500.zip
	unzip -o -q $(@D)/cities500.zip cities500.txt -d $(@D)

places: processing/places/places.csv

processing/places/places.csv: manual/known_places.csv $(wildcard manual/place_picks.csv) processing/track/points.csv \
    scripts/places.py $(COMMON) | processing/geonames/cities500.txt
	$(PY) scripts/places.py

stays: processing/stays/found.json

processing/stays/found.json: processing/track/points.csv scripts/stays.py $(COMMON) | processing/geonames/cities500.txt
	$(PY) scripts/stays.py

route: processing/route/route.csv

processing/route/route.csv: processing/track/points.csv processing/places/places.csv manual/stays.csv \
    manual/travel_modes.csv $(wildcard manual/ignored_photos.csv) scripts/route.py $(COMMON) \
    | processing/osm/valhalla/valhalla.json
	$(PY) scripts/route.py

processing/osm/valhalla/valhalla.json:
	@echo "$@ is missing: run make osm (a few hours, once)" >&2; exit 1

# Prints how many of each finding are left to look at
check: processing/route/findings.json

processing/route/findings.json: processing/route/route.csv manual/dismissed.csv scripts/checks.py $(COMMON)
	$(PY) scripts/checks.py

locate: processing/located/audio.csv

processing/located/audio.csv: processing/route/route.csv processing/places/places.csv scripts/locate.py $(COMMON) \
    $(wildcard processing/asr/*/*.json)
	$(PY) scripts/locate.py

# Transcription; each skips what's done, so it can be stopped and run again
audio: | index
	$(PY) scripts/transcribe.py compress

transcripts: audio locate
	$(PY) scripts/transcribe.py run

transcripts-pilot: audio locate
	$(PY) scripts/transcribe.py pilot

languages: audio
	$(PY) scripts/transcribe.py languages

ACTION ?= status
transcripts-remote: | $(VENV)/.installed
	$(PY) scripts/transcribe.py remote $(ACTION)

# Claude splits each entry into events. Entries already done are skipped, so run it again after
# it stops at the subscription's usage limit. After changing the tags: make events ARGS=--redo-stale
ARGS ?=
events: locate
	$(PY) scripts/events.py $(ARGS)

# The review app: one server, opened in the browser. Run it again to see rebuilt outputs;
# the app's Rebuild button runs the steps it needs itself
STORY ?=
review: | $(VENV)/.installed
	$(PY) scripts/review/server.py $(if $(STORY),--story $(STORY))

# The book
STORIES := $(patsubst raw/stories/%.md,processing/story_tex/%.tex,$(wildcard raw/stories/*.md))
LATEX := xelatex -interaction=nonstopmode -halt-on-error -output-directory=processing/book_tex

book: book.pdf

clean/stories/%.md: raw/stories/%.md scripts/cleaners/stories.py scripts/cleaners/_story_text.py | $(VENV)/.installed
	@$(PY) scripts/build_clean.py

processing/story_tex/%.tex: clean/stories/%.md
	@mkdir -p $(@D)
	pandoc --from markdown --to latex --wrap preserve --output $@ $<

# Twice, so the table of contents catches up; on failure show the log's error
book.pdf: book.tex $(STORIES)
	@mkdir -p processing/book_tex
	@echo "xelatex book.tex"
	@$(LATEX) book.tex >/dev/null && $(LATEX) book.tex >/dev/null \
	  || { grep -A5 '^!' processing/book_tex/book.log; exit 1; }
	@cp processing/book_tex/book.pdf $@

counts: clean-data
	@$(PY) scripts/counts.py

PERIOD ?=
progress: | $(VENV)/.installed
	@$(PY) scripts/progress.py --plot $(if $(PERIOD),--period $(PERIOD))

# Downloads into the raw data's own directories
fetch-komoot: | $(VENV)/.installed
	$(PY) scripts/fetch.py gpx

fetch-meta: | $(VENV)/.installed
	$(PY) scripts/fetch.py meta

# Outputs in processing/ that clean keeps: slow to regenerate (downloads, hours of compute,
# paid APIs). Your answers are in manual/, which nothing removes
KEEP := osm geonames asr audio events thumbs story

clean:
	rm -rf clean book.pdf
	find processing -mindepth 1 -maxdepth 1 $(KEEP:%=-not -name %) -exec rm -rf {} + 2>/dev/null || true

# Remove everything, kept outputs included
purge:
	rm -rf clean processing book.pdf
