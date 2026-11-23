# Travel book: A book of stories from a two-year bike trip, and the pipeline that places every ride, photo and diary entry on the route
#
#   raw/...                    source data, only ever read: small files tracked in git,
#                              the rest mounted read-only from outside the repo
#     -> clean/...             the same tree, ready to use: what a cleaner in scripts/clean/
#                              claims is rewritten, the rest are symlinks to raw/  (make clean-data)
#     -> processing/index/files.csv, <indexer>.csv: every file in clean/, where it came
#                              from, and what's in it, from scripts/index/        (make index)
#
#   Add a line here for each output: what it's made from, and its make target.
#
#   Raw data kept outside the repo is bind-mounted read-only at the paths in
#   mounts.toml (make mounts to set up, make mount / unmount): each raw/ mount
#   point is a symlink to the mount in the hidden .mounts/, which keeps it out
#   of the file manager's sidebar. The config and mount points are local to
#   this machine and never committed.
#   Every make run first mounts any that aren't mounted yet.
#
#   Settings: defaults in settings.yaml, typed and loaded by scripts/settings.py
#   (pydantic-settings). SETTINGS_<NAME>=<value> make ... overrides one for a run.
#   Secrets are read from the system keyring (make secret NAME=<name> to store one),
#   or from ~/.secrets/<name> where there's no keyring.
#
#   make hooks turns on the git hooks that check the SRS and SDD (see CONTRIBUTING.md).
#
#   make clean removes what's quick to rebuild. make purge removes everything,
#   including the slow outputs and your answers in processing/, listed in KEEP.
#
# Hidden files are ignored throughout. Names have no whitespace, raw/ included:
# make can't handle it. scripts/rename_spaces.py renames raw data at its source.

# Mount any raw data that isn't mounted yet, before anything looks for it.
# A failure doesn't stop make, so targets that don't need it still build.
ifeq ($(filter help hooks mounts mount unmount mount-status apt secret,$(MAKECMDGOALS)),)
$(shell python3 scripts/mounts.py mount >&2)
endif

# Python tools come from .venv, rebuilt whenever requirements.txt changes
VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: all help hooks venv apt mounts mount unmount mount-status secret clean-data index clean purge
.DELETE_ON_ERROR:

all: index

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

# Outputs in processing/ that clean keeps: slow to regenerate, or your answers
KEEP :=

clean:
	rm -rf clean
	find processing -mindepth 1 -maxdepth 1 $(KEEP:%=-not -name %) -exec rm -rf {} + 2>/dev/null || true

# Remove everything, kept outputs included
purge:
	rm -rf clean processing
