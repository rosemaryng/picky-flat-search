# flat-finder — an autonomous London rental agent

> Built for the **Cursor "Hands Off" Hackathon**: a self-running business where AI
> agents do the work. You write a brief in plain English, walk away, and the agent
> hunts listings, enriches them with data humans never check (EPC, floorplan, commute,
> nearby gyms/shops), scores them against your wishlist, and drafts the enquiry to
> register interest / book a viewing.

```
brief (free text)  ─▶  collect  ─▶  enrich  ─▶  score  ─▶  draft enquiry  ─▶  dashboard
                       Rightmove     EPC API     LLM /        LLM /            + PayPal
                       OnTheMarket   floorplan    rules        template         revenue
                                     commute/POI
   ▲ runs unattended on Modal (cron) · shared state in modal.Dict · money via PayPal ▲
```

## Why it fits the hackathon
- **Autonomous:** the `scan` loop runs on a schedule with no human in the loop.
- **Makes money:** renters pay (PayPal) for the Pro feed + auto-enquiries.
- **Measurable:** the dashboard shows listings seen, matches, and £ revenue.

## Quickstart (zero keys, runs offline)
The core pipeline is **stdlib-only** and ships with deterministic fallbacks, so it
runs with no API keys at all.

```bash
pip install -r requirements.txt        # only needed for the web UI / integrations
python run_local.py                    # pulls real London listings, scores a demo brief
python -m web.app                      # dashboard at http://localhost:5000
```

`run_local.py` pulls live listings, enriches the top few (commute time via TfL,
nearby POIs via OpenStreetMap), scores them against a demo brief, and prints a
ranked shortlist with reasons. Results persist to `local_db.json` and render in
the dashboard.

### Run locally (one command)
If you have `make`, the fastest path is `make setup && make web`, then open
http://localhost:5000. See **[docs/LOCAL_DEV.md](docs/LOCAL_DEV.md)** for
copy-paste steps (macOS, Linux, and Windows PowerShell) plus troubleshooting.

## Add real intelligence (optional keys)
Drop these into `.env` (see `.env.example`) and the matching upgrades turn on
automatically:

| Key | Unlocks |
|---|---|
| `OPENAI_API_KEY` | LLM brief-parsing, **floorplan vision** (sqm/aspect), nuanced scoring, human-quality enquiry drafts |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Shared Postgres store (schema in [`supabase_schema.sql`](supabase_schema.sql)). Auto-selected when set. |
| `FLATFINDER_STORE` | Force a store backend: `supabase` \| `modal` (named `modal.Dict`) \| `local`. Default auto-picks Supabase → modal.Dict → local JSON. |
| `PAYPAL_CLIENT_ID` / `PAYPAL_SECRET` | Real (sandbox) checkout; else payments are simulated |
| `EPC_API_KEY` | Official gov EPC rating + floor area by postcode |
| `TFL_APP_KEY` | Higher TfL rate limits |

## Deploy hands-off (Modal)
```bash
pip install modal && modal token new
modal secret create flatfinder-secrets OPENAI_API_KEY=... \
    PAYPAL_CLIENT_ID=... PAYPAL_SECRET=...
modal deploy app_modal.py     # scan() now runs every hour, unattended
```
- `scan` — scheduled monitor (collect → enrich → match → draft)
- `submit` — on-demand register-interest / viewing request for one match
- `web` — the dashboard as a Modal web endpoint

## Layout
```
flatfinder/
  collectors/   rightmove.py, onthemarket.py  (+ base parser)
  enrich/       epc.py, floorplan.py (vision), geo.py (commute + POIs)
  brief.py      free-text  -> structured Brief (LLM or heuristic)
  scoring.py    listing × brief -> score + reasons (LLM or rules)
  enquiry.py    draft (+ optional Playwright submit, off by default)
  store.py      shared modal.Dict or local-JSON store (same interface)
  pipeline.py   the hands-off loop
payments/paypal.py     sandbox checkout + capture
web/app.py             Flask dashboard
app_modal.py           Modal deployment
```

## Important caveats (read before going to production)
- **Portal ToS / scraping.** Rightmove & Zoopla forbid scraping and block bots
  (Zoopla already 403s). The collectors here are for the **demo** — for a real
  product, switch the data layer to **parsing the portals' own email alerts** or a
  licensed feed. The store/collector split makes this swap easy.
- **Auto-submitting enquiries** can breach ToS, hit CAPTCHAs, and annoy agents.
  It is **disabled by default** (`ALLOW_AUTO_SUBMIT`); the intended UX is
  "agent drafts → you approve → send". Auto-acting *as* a tenant also raises
  impersonation/wasted-viewing concerns — keep a human approval step.
- **"Window facing" / orientation** is often a best-effort estimate (from the
  floorplan's compass arrow), not ground truth.

## License
MIT — hackathon prototype, not investment or housing advice.
