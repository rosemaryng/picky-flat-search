#!/usr/bin/env bash
#
# dev.sh — one command to set up flat-finder and launch the dashboard.
#
#   ./scripts/dev.sh
#
# Creates a local virtualenv, installs requirements, then serves the
# dashboard at http://localhost:5000. No API keys required.
set -euo pipefail

# Always run from the repo root (parent of this script's directory).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV=".venv"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Check for Python 3.10+ -------------------------------------------------
PYBIN=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
      PYBIN="$cand"
      break
    fi
  fi
done

if [ -z "$PYBIN" ]; then
  fail "Python 3.10+ is required but was not found.
       macOS:   brew install python
       Windows: install from https://www.python.org/downloads/ (tick 'Add to PATH')"
fi

say "Using $("$PYBIN" --version 2>&1) at $(command -v "$PYBIN")"

# --- 2. Create the virtualenv --------------------------------------------------
if [ ! -d "$VENV" ]; then
  say "Creating virtualenv in $VENV"
  "$PYBIN" -m venv "$VENV"
else
  say "Reusing existing virtualenv in $VENV"
fi

# venv layout differs on Windows (Git Bash) vs. macOS/Linux.
if [ -x "$VENV/bin/python" ]; then
  VENV_PY="$VENV/bin/python"
else
  VENV_PY="$VENV/Scripts/python.exe"
fi

# --- 3. Install dependencies ---------------------------------------------------
say "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip >/dev/null

say "Installing requirements (this can take a minute the first time)"
"$VENV_PY" -m pip install -r requirements.txt

# --- 4. Launch the dashboard ---------------------------------------------------
say "Setup complete!"
echo "    Dashboard:  http://localhost:5000"
echo "    Stop it:    press Ctrl+C"
echo "    Run the demo instead:  $VENV_PY run_local.py"
say "Starting the dashboard…"
exec "$VENV_PY" -m web.app
