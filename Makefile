# flat-finder — local dev convenience targets
# Quickstart:  make setup  &&  make web   ->  http://localhost:5000
# No API keys required — the pipeline ships with offline fallbacks.

VENV    := .venv
PYTHON  := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip

# Interpreter used to create the venv (must be Python 3.10+).
# Auto-picks the newest available; override with e.g. `make setup PY=python3.12`.
PY ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3 || command -v python)

.DEFAULT_GOAL := help
.PHONY: help setup demo web all clean

# Show this help
help:
	@echo "flat-finder — make targets:"
	@echo "  make setup   Create a .venv and install requirements"
	@echo "  make demo    Run the pipeline once and print ranked matches"
	@echo "  make web     Serve the dashboard at http://localhost:5000"
	@echo "  make all     setup + demo, then launch the dashboard"
	@echo "  make clean   Remove the virtualenv and local demo database"

$(PYTHON):
	@test -n "$(PY)" || { echo "ERROR: no python found. Install Python 3.10+."; exit 1; }
	@$(PY) -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' || { \
		echo "ERROR: Python 3.10+ is required, but '$(PY)' is $$($(PY) --version 2>&1)."; \
		echo "  macOS:  brew install python@3.12   (or: pyenv install 3.12 && pyenv local 3.12)"; \
		echo "  Then:   make clean && make setup"; \
		echo "  Or point make at a newer interpreter: make setup PY=python3.12"; \
		exit 1; }
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip

# Create venv + install requirements
setup: $(PYTHON)
	$(PIP) install -r requirements.txt
	@echo "Setup complete. Next: 'make demo' or 'make web'."

# Run the pipeline once and print ranked matches
demo: setup
	$(PYTHON) run_local.py

# Serve the dashboard at http://localhost:5000
web: setup
	@echo "Dashboard starting at http://localhost:5000 (Ctrl+C to stop)"
	$(PYTHON) -m web.app

# setup + demo, then launch the dashboard
all: setup demo web

# Remove the virtualenv and local demo database
clean:
	rm -rf $(VENV) local_db.json
