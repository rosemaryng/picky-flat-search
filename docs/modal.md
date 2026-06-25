# Modal deployment runbook (Track B)

This is the "hands off" engine: [`app_modal.py`](../app_modal.py) deploys the
flat-finder to [Modal](https://modal.com) so the `scan` loop runs **every hour,
unattended**, with shared state in a named `modal.Dict`.

## What gets deployed

| Function     | Type                         | Purpose |
|--------------|------------------------------|---------|
| `scan`       | scheduled (`Period(hours=1)`) | pull → enrich → score → draft, unattended |
| `trigger`    | on-demand                    | run a scan immediately (same logic as `scan`) |
| `seed_brief` | on-demand                    | put a brief into the shared store |
| `submit`     | on-demand                    | register interest / book a viewing for one match |
| `web`        | WSGI web endpoint            | the dashboard |
| `main`       | `@app.local_entrypoint`      | local driver: run a scan (optionally seed first) |

All of `scan`/`trigger`/`seed_brief` route through the pure helpers
`run_scan_cycle` / `seed_brief_cycle`, which have **no Modal dependency** and are
unit-tested offline in [`tests/test_modal.py`](../tests/test_modal.py).

## 1. Install & authenticate

```bash
pip install modal          # not needed for the offline core; only for deploy
modal token new            # opens a browser to link your Modal account
```

`app_modal.py` is import-safe **without** `modal` installed (the helpers still
work), so `ruff check .` and `python -m pytest -q` pass with no Modal account.

## 2. Create the shared secret

```bash
modal secret create flatfinder-secrets \
    OPENAI_API_KEY=sk-...        \
    PAYPAL_CLIENT_ID=...         \
    PAYPAL_SECRET=...            \
    FLATFINDER_STORE=modal
```

All keys are **optional** — the pipeline ships with deterministic offline
fallbacks. If the secret is missing entirely, the app logs a warning and deploys
without it (`secrets = []`); `scan` still runs using the offline fallbacks.

## 3. Deploy

```bash
modal deploy app_modal.py
```

After this, `scan()` runs automatically every hour. The dashboard URL for `web`
is printed at the end of the deploy.

## 4. Run a scan on demand

```bash
modal run app_modal.py                 # local entrypoint → runs scan.remote()
modal run app_modal.py --seed \
    --text "1 bed Hackney up to £2500, must have lift"   # seed a brief, then scan
modal run app_modal.py::trigger        # call the on-demand scan function directly
modal run app_modal.py::seed_brief --text "2 bed Islington up to £2800"
```

## 5. Watch logs

```bash
modal app logs flat-finder             # live tail of all functions
```

Each scan emits one structured line you can grep/parse, e.g.:

```
2026-06-25 19:20:00 INFO flatfinder.modal scan complete {"briefs": 1, "listings": 42, "new": 7, "matches": 3}
```

- `briefs`   — briefs scanned this cycle
- `listings` — total listings known to the shared store after the scan
- `new`      — listings added this cycle (delta in the store)
- `matches`  — matches scoring above threshold this cycle

Set `FLATFINDER_LOG_LEVEL=DEBUG` (env/secret) for more verbosity.

> Note: the per-cycle `new`/`listings` counts are derived from `store.stats()`
> before/after the run, because the public store interface does not expose the
> raw "pulled" count. Surfacing pulled-vs-new precisely would need either a new
> store method or a richer return from `run_scan` (owned by Track A) — see the
> PR description.

## 6. How the hourly schedule works

`scan` is decorated with `schedule=modal.Period(hours=1)`, so Modal invokes it
once an hour with no human in the loop. Each run:

1. writes an **agent heartbeat** via `store.set_agent_status("scan", "running")`,
2. loads briefs from the shared store (falling back to the demo brief),
3. runs the pipeline (`collect → enrich → score → draft`),
4. logs the structured report and refreshes the heartbeat to `"idle"` with
   `last_run`, `last_matches`, `last_new`, `last_listings` (or `"error"` on
   failure, so a stuck agent is visible to other agents).

## How the shared `modal.Dict` coordinates agents

State is a single **named** `modal.Dict` (`flatfinder-shared`, override with
`MODAL_DICT_NAME`). Every worker that does
`modal.Dict.from_name("flatfinder-shared", create_if_missing=True)` attaches to
the *same* live dictionary, so it is genuine cross-agent shared memory, not a
per-worker copy. Keys are namespaced so the dict doubles as a coordination
blackboard:

```
brief:<id>     listing:<id>     match:<brief>::<listing>
payment:<id>   agent:<name>     note:<key>
```

This means:

- The hourly `scan`, an on-demand `trigger`, the `web` dashboard, and any other
  Devin/Modal agent in the workspace all read and write the **same** briefs,
  listings, matches and `agent:*` heartbeats.
- `seed_brief` writing `brief:<id>` is immediately visible to the next `scan`.
- `set_agent_status("scan", ...)` writes `agent:scan`, so other agents can see
  whether the scanner is `running`/`idle`/`error` and when it last ran — the
  basis for hand-off between agents.

The backend is selected with `FLATFINDER_STORE=modal` (set automatically in the
Modal image and re-asserted at the top of each function). Offline, the same
interface is served by `LocalStore` (a JSON file), which is how the tests
exercise the coordination logic without a Modal account.

## Troubleshooting

- **`modal.Dict` / secret missing** — handled gracefully: `get_store()` falls
  back to `LocalStore`, missing secrets are logged and skipped, and heartbeat
  writes are wrapped so a read-only/absent store never crashes a scan.
- **Auth errors** — re-run `modal token new`.
- **Nothing matches** — lower the threshold or seed a broader brief with
  `seed_brief`; check the `scan complete {...}` log line for `new`/`matches`.
