"""Modal deployment — the 'hands off' engine.

    modal token new
    modal secret create flatfinder-secrets OPENAI_API_KEY=... SUPABASE_URL=... \
        SUPABASE_SERVICE_KEY=... PAYPAL_CLIENT_ID=... PAYPAL_SECRET=...
    modal deploy app_modal.py     # scan() then runs every 15 min, unattended

`scan` monitors portals; `submit` registers interest on demand; `web` serves the
dashboard. All state lives in Supabase so it persists across runs.
"""
import modal

image = (
    modal.Image.debian_slim()
    .pip_install("supabase", "openai", "flask")
    .add_local_python_source("flatfinder", "payments", "web")
)

app = modal.App("flat-finder")

try:
    secrets = [modal.Secret.from_name("flatfinder-secrets")]
except Exception:
    secrets = []


@app.function(image=image, schedule=modal.Period(minutes=15), secrets=secrets, timeout=600)
def scan():
    """Runs unattended on a schedule: pull -> enrich -> match -> draft."""
    from flatfinder.models import Brief
    from flatfinder.pipeline import demo_brief, run_scan
    from flatfinder.store import get_store

    store = get_store()
    rows = store.briefs()
    briefs = [Brief(**{k: r.get(k) for k in Brief.__dataclass_fields__ if k in r})
              for r in rows] or [demo_brief()]
    matches = run_scan(briefs, store=store)
    return [{"score": m.score, "address": m.listing.address, "url": m.listing.url}
            for m in matches]


@app.function(image=image, secrets=secrets)
def submit(brief_id: str, listing_id: str):
    """On-demand: register interest / request a viewing for one match."""
    from flatfinder.enquiry import submit_enquiry
    from flatfinder.models import Listing, Match
    from flatfinder.store import get_store

    store = get_store()
    for m in store.matches():
        if m["brief_id"] == brief_id and m["listing"]["id"] == listing_id:
            match = Match(brief_id=brief_id, listing=Listing(**m["listing"]),
                          score=m["score"], reasons=m["reasons"],
                          enquiry_draft=m["enquiry_draft"])
            return submit_enquiry(match)
    return "match not found"


@app.function(image=image, secrets=secrets)
@modal.wsgi_app()
def web():
    from web.app import create_app
    return create_app()
