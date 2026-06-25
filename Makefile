# flat-finder — local dev convenience targets
# Quickstart:  make setup  &&  make web   ->  http://localhost:5000
# No API keys required — the pipeline ships with offline fallbacks.

VENV    := .venv
PYTHON  := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip

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
	python3 -m venv $(VENV)
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
