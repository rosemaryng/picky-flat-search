# Run flat-finder locally

Get the dashboard running on your own laptop in a couple of minutes. **No API
keys are needed** — the pipeline ships with offline fallbacks, so everything
works out of the box.

You only need **Python 3.10+** and **git** installed.

---

## macOS / Linux (copy-paste)

```bash
git clone https://github.com/rosemaryng/picky-flat-search
cd picky-flat-search
make setup
make web
```

Then open **http://localhost:5000** in your browser.

Prefer one command? This does setup *and* launches the dashboard:

```bash
./scripts/dev.sh
```

Want to see the ranked shortlist printed in your terminal first?

```bash
make demo
```

---

## Windows (PowerShell)

Windows does not ship `make`, so run the steps directly. (Git Bash users can
instead run `./scripts/dev.sh`.)

```powershell
git clone https://github.com/rosemaryng/picky-flat-search
cd picky-flat-search
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m web.app
```

Then open **http://localhost:5000** in your browser.

Run the demo pipeline instead of the dashboard:

```powershell
python run_local.py
```

> If `python` is not found, try `py -3` instead, or install Python from
> https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.

---

## No keys needed

The core pipeline is **stdlib-only** and runs offline with deterministic
fallbacks, so it works with **zero API keys**. Optional keys (OpenAI, Supabase,
PayPal, EPC, TfL) only unlock extra intelligence — see the table in the
[README](../README.md#add-real-intelligence-optional-keys). To add them later,
copy `.env.example` to `.env` and fill in what you have.

---

## Troubleshooting

### Port 5000 is already in use
On macOS, AirPlay Receiver listens on port 5000. Either turn it off in
**System Settings → General → AirDrop & Handoff → AirPlay Receiver**, or stop
whatever is using the port:

```bash
lsof -i :5000           # see what's using it
kill <PID>              # stop that process
```

On Windows (PowerShell):

```powershell
Get-NetTCPConnection -LocalPort 5000 | Select-Object -ExpandProperty OwningProcess
Stop-Process -Id <PID>
```

### "python: command not found" or wrong version
Check your version with `python3 --version` (macOS/Linux) or `python --version`
(Windows). You need **3.10 or newer**.

- macOS: `brew install python`
- Windows: install from https://www.python.org/downloads/ and tick
  **"Add python.exe to PATH"**, then reopen your terminal.

`./scripts/dev.sh` checks this for you and prints a clear message if Python is
too old or missing.

### "make: command not found"
`make` is preinstalled on macOS (via the Xcode command line tools — run
`xcode-select --install` if prompted) and Linux. On Windows, either use the
PowerShell steps above or run `./scripts/dev.sh` from Git Bash.

### "pip: command not found" / pip errors
Use pip *through* Python so you always hit the right interpreter:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

The `make setup` target and `scripts/dev.sh` already do this inside the
project's `.venv`.

### Start over from a clean slate
```bash
make clean    # removes .venv and the local demo database, then re-run make setup
```
