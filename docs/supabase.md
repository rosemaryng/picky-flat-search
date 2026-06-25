# Supabase store — setup runbook

flat-finder runs fully offline with a local JSON store by default. Point it at a
**Supabase** (Postgres) project and every agent — Modal workers, other Devin
sessions, the dashboard — shares the *same* live state: listings, matches,
briefs, payments, the agent/notes coordination blackboard, and a persistent
enrichment cache (EPC / commute / POIs).

The backend lives in [`flatfinder/store.py`](../flatfinder/store.py)
(`SupabaseStore`) and the schema in
[`supabase_schema.sql`](../supabase_schema.sql). `get_store()` **auto-selects**
Supabase as soon as `SUPABASE_URL` and a key are set — no code change needed.

---

## 1. Create a Supabase project

1. Go to <https://supabase.com> and sign in (free tier is plenty).
2. **New project** → pick an org, name it (e.g. `flat-finder`), set a strong
   database password, choose a region near you, and create it.
3. Wait ~2 minutes for the database to finish provisioning.

## 2. Run the schema

1. In the project, open **SQL Editor** (left sidebar) → **New query**.
2. Copy the entire contents of [`supabase_schema.sql`](../supabase_schema.sql)
   into the editor and click **Run**.
3. It's idempotent (`create table if not exists` / `create index if not exists`),
   so it's safe to re-run after pulling schema updates.
4. Verify under **Table Editor** that these tables exist: `briefs`, `listings`,
   `matches`, `viewings`, `payments`, `agents`, `notes`, `enrichment_cache`.

## 3. Get the URL + service key

1. Open **Project Settings → API**.
2. Copy two values:
   - **Project URL** → `SUPABASE_URL`
     (looks like `https://abcdefgh.supabase.co`).
   - **Project API keys → `service_role` secret** → `SUPABASE_SERVICE_KEY`.

> **Why the service role?** The agents run server-side (Modal cron, CLI) with no
> logged-in user, so they need to bypass Row Level Security. The `service_role`
> key does that. Treat it like a database password: **server-side only, never
> ship it to a browser/client and never commit it**. The store also accepts
> `SUPABASE_KEY` as a fallback name (see
> [`flatfinder/config.py`](../flatfinder/config.py)).

## 4. Set the environment variables

Add them to your `.env` (copy from [`.env.example`](../.env.example)):

```bash
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOi...   # service_role secret
```

Install the client if you haven't:

```bash
pip install -r requirements.txt   # includes supabase>=2.5
```

For the hands-off Modal deployment, put the same values in the Modal secret so
every worker picks them up:

```bash
modal secret create flatfinder-secrets \
    SUPABASE_URL=https://abcdefgh.supabase.co \
    SUPABASE_SERVICE_KEY=eyJhbGciOi...
```

## 5. Confirm Supabase is selected

`get_store()` auto-detects Supabase when both vars are present (you can also force
it with `FLATFINDER_STORE=supabase`). Quick check:

```bash
python -c "from flatfinder.store import get_store; print(type(get_store()).__name__)"
# -> SupabaseStore
```

Then run the pipeline and confirm rows land in Supabase:

```bash
python run_local.py
```

Open **Table Editor → listings / matches** in Supabase — you should see rows.

### Backend selection order

| `FLATFINDER_STORE` | Result |
|---|---|
| `local` | always the local JSON store |
| `supabase` | force Supabase (errors if unreachable, then falls back to local) |
| `modal` | shared `modal.Dict` (requires a Modal context) |
| *(unset)* | **auto:** Supabase if `SUPABASE_URL` + key are set, else local JSON |

If the Supabase client can't connect, `get_store()` logs a warning and falls
back to the local store, so the app keeps running offline.

## Troubleshooting

- **`SupabaseStore unavailable ... falling back`** — `SUPABASE_URL`/key missing
  or wrong, or `supabase` not installed (`pip install -r requirements.txt`).
- **`column ... does not exist` (400)** — the schema is out of date; re-run
  `supabase_schema.sql`. The store only ever writes declared columns plus a
  `data`/`raw` jsonb payload (see `_flat_listing` / `_flat_brief` /
  `_flat_payment` and `tests/test_supabase.py`, which assert this).
- **Permission denied / RLS errors** — you're using the `anon` key; switch to the
  `service_role` secret for server-side agents.

## What's stored where

| Table | Written by | Notes |
|---|---|---|
| `briefs` | `upsert_brief` | schema columns + full brief (incl. `contact_*`) in `data` |
| `listings` | `upsert_listing` | schema columns + full listing in `data` |
| `matches` | `add_match` | nested `listing` jsonb so consumers need no join; indexed on `score desc` |
| `payments` | `record_payment` | schema columns + full payload in `raw`; powers `revenue()` |
| `agents` | `set_agent_status` | cross-agent status blackboard |
| `notes` | `put_note` | free-form coordination key/value |
| `enrichment_cache` | `cache_enrichment` / `get_enrichment` | EPC / commute / POI results persist across runs and agents |
