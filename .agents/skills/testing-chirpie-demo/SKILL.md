---
name: testing-chirpie-demo
description: Deploy, seed, and test the Chirpie (flat-finder) dashboard golden path on Modal. Use when verifying UI/branding, scoring/bird-voice, demo nests, or the Search/Start-Scouting flow.
---

# Testing the Chirpie (flat-finder) demo

Chirpie is the bird-themed rebrand of the autonomous London flat-finder. The demo
golden path is **User → Modal scan / seed → Dashboard**.

## Where things live
- Deployed dashboard (Modal): `https://rosemaryng--flat-finder-web.modal.run`
- Flask app + routes: `web/app.py` (`/api/trigger`, `/api/seed-demo`, `/api/status`).
- UI template: `web/templates/index.html` (all branding/copy/CSS).
- Scorer + bird-voice reasons: `flatfinder/scoring.py` (`_chirpie_verdict`).
- Demo safety-net listings: `app_modal.py` `demo_listings()` / `seed_demo_data()`.
- The **brief is code-defined** in `flatfinder/pipeline.py` `demo_brief()` — there is
  **no free-text brief input box** on the dashboard yet. To demo a specific brief,
  edit `demo_brief()` (and tailor `demo_listings()` to match) so the seeded nests
  score ~100 against it, then redeploy + reseed.

## Deploy + seed (Modal)
Needs Modal auth (token id/secret — see Devin Secrets below):
```bash
export MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=...
python -m modal deploy app_modal.py          # redeploy after any code change
python -m modal run app_modal.py::seed_demo  # seed the 3 perfect demo nests
```

## Reset state for a clean demo
The shared store is a named `modal.Dict` (`flatfinder-shared`). Old/live listings
accumulate and clutter the demo. Clear it before recording:
```bash
python -c "import modal; d=modal.Dict.from_name('flatfinder-shared', create_if_missing=True); d.clear()"
```
Then either click **Load demo nests** in the UI or run the `seed_demo` function.

## Gotchas
- **Browser cache**: Modal may serve a stale dashboard after redeploy. A single
  `Ctrl+Shift+R` (or a changing `?cb=<ts>` query) is usually needed; verify the
  true server response with `curl -s "$URL/?cb=$RANDOM" | grep -o Chirpie`.
- **Scoring must-haves**: `_feature_state` matches must-have keywords as substrings
  of address+summary+property_type (or structured fields like supermarket/lift).
  If a demo listing should pass a must-have, ensure the keyword literally appears
  (e.g. use `period` not `period conversion` so a "period house" also matches).
- Bird-voice highlight: the template applies the yellow `.love` pill when a reason
  contains `Chirpie`, so scorer headlines must include that word.

## Verify locally (zero keys)
```bash
ruff check . && python -m pytest -q          # expect lint clean, 90 passed
FLATFINDER_STORE=local python -m web.app     # dashboard at localhost:5000
```
Quick score check for demo data against the brief:
```bash
python -c "from app_modal import demo_listings; from flatfinder.pipeline import demo_brief; from flatfinder.scoring import score; b=demo_brief(); [print(round(score(l,b)[0]), l.address) for l in demo_listings()]"
```

## Golden-path test checklist
1. Empty state shows Chirpie branding (sky/cloud/beak), no `revenue` stat.
2. Load demo nests → 3 nests matching the brief area, all score 100.
3. Reasons use bird voice ("Chirpie loves this one!", "just a hop, skip & a jump").
4. Enquiry draft renders in a readonly textarea.
5. Start Scouting flips the button to "Chirpie is flying… 🕊️".

## Devin Secrets Needed
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` — to deploy/seed/clear on Modal.
- `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET` (sandbox) — only for real sandbox checkout;
  the dashboard simulates payments without them.
