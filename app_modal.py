"""Modal deployment — the 'hands off' engine.

    pip install modal
    modal token new
    modal secret create flatfinder-secrets OPENAI_API_KEY=... \
        PAYPAL_CLIENT_ID=... PAYPAL_SECRET=... FLATFINDER_STORE=modal
    modal deploy app_modal.py     # scan() then runs every hour, unattended

`scan` monitors portals on a schedule; `trigger` runs a scan on demand;
`seed_brief` drops a brief into shared state; `submit` registers interest;
`web` serves the dashboard. State lives in a shared `modal.Dict` (see
flatfinder/store.py) that every agent in this Modal workspace can read/write.

The module is import-safe **without** the `modal` package installed: the pure
helpers below have no Modal dependency, so they (and the runbook in
docs/modal.md) can be exercised offline. The Modal functions are only defined
when `modal` is importable. See docs/modal.md for the full runbook.
"""
import json
import logging
import os
import time

logging.basicConfig(
    level=os.environ.get("FLATFINDER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("flatfinder.modal")


# --------------------------------------------------------------------------- #
# Pure helpers — no Modal dependency, unit-tested in tests/test_modal.py.       #
# --------------------------------------------------------------------------- #
def briefs_from_rows(rows):
    """Convert stored brief rows -> `Brief` objects, falling back to the demo brief.

    Only keys that are real `Brief` dataclass fields are passed through, and rows
    without an `id` are skipped, so malformed shared-state entries can't crash a
    scan. Returns at least one brief so an unattended scan always has work to do.
    """
    from flatfinder.models import Brief
    from flatfinder.pipeline import demo_brief

    briefs = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        fields = {k: row[k] for k in Brief.__dataclass_fields__ if k in row}
        briefs.append(Brief(**fields))
    return briefs or [demo_brief()]


def matches_payload(matches):
    """Serialise `Match` objects to a JSON-safe shortlist."""
    return [
        {"score": m.score, "address": m.listing.address, "url": m.listing.url}
        for m in matches
    ]


def scan_report(n_briefs, listings_before, listings_after, n_matches):
    """Build the structured per-scan record (listings pulled, new, matches)."""
    return {
        "briefs": n_briefs,
        "listings": listings_after,
        "new": max(listings_after - listings_before, 0),
        "matches": n_matches,
    }


def _listing_count(store):
    """Best-effort total listings known to the store (0 if unsupported)."""
    try:
        return int(store.stats().get("listings", 0))
    except Exception as e:  # a store backend may not implement stats()
        logger.warning("store.stats() unavailable: %r", e)
        return 0


def _set_status(store, status, **extra):
    """Refresh the 'scan' agent heartbeat, tolerating a read-only/missing store."""
    try:
        store.set_agent_status("scan", status, **extra)
    except Exception as e:
        logger.warning("could not write agent heartbeat (%s): %r", status, e)


def run_scan_cycle(store=None, briefs=None):
    """Core of `scan()`: pull -> enrich -> match, with structured logging and a
    refreshed agent heartbeat. Works with any store implementing the standard
    interface (e.g. `LocalStore` in tests), so it runs fully offline.

    Returns the JSON-safe match shortlist (see `matches_payload`).
    """
    from flatfinder.pipeline import run_scan
    from flatfinder.store import get_store

    store = store or get_store()
    _set_status(store, "running", started_at=time.time())
    try:
        before = _listing_count(store)
        briefs = briefs or briefs_from_rows(store.briefs())
        matches = run_scan(briefs, store=store)
        report = scan_report(len(briefs), before, _listing_count(store), len(matches))
        logger.info("scan complete %s", json.dumps(report))
        _set_status(
            store,
            "idle",
            last_run=time.time(),
            last_matches=report["matches"],
            last_new=report["new"],
            last_listings=report["listings"],
        )
        return matches_payload(matches)
    except Exception as e:
        logger.exception("scan failed: %r", e)
        _set_status(store, "error", last_run=time.time(), error=str(e))
        raise


def seed_brief_cycle(text=None, brief_id="brief-demo", store=None):
    """Put a brief into the shared store. Uses the demo brief when no text given."""
    from flatfinder.brief import parse
    from flatfinder.pipeline import demo_brief
    from flatfinder.store import get_store

    store = store or get_store()
    brief = parse(text, id=brief_id) if text else demo_brief()
    store.upsert_brief(brief.to_dict())
    _set_status(store, "idle", action="seed_brief", brief_id=brief.id, last_run=time.time())
    logger.info("seeded brief %s", brief.id)
    return brief.to_dict()


# --------------------------------------------------------------------------- #
# Modal wiring — only defined when the `modal` package is importable.           #
# --------------------------------------------------------------------------- #
try:
    import modal
except ModuleNotFoundError:  # keep the module import-safe offline
    modal = None
    logger.info("`modal` not installed; Modal functions disabled (helpers still usable)")

if modal is not None:
    image = (
        modal.Image.debian_slim()
        .pip_install("openai", "flask")
        .env({"FLATFINDER_STORE": "modal"})  # use the shared modal.Dict store
        .add_local_python_source("flatfinder", "payments", "web")
        # Jinja templates aren't .py files, so the package mount above skips them.
        # Ship them to a dedicated path and point Flask at it via FLATFINDER_TEMPLATE_DIR.
        .add_local_dir("web/templates", remote_path="/assets/web_templates")
    )

    app = modal.App("flat-finder")

    try:
        secrets = [modal.Secret.from_name("flatfinder-secrets")]
    except Exception as e:
        logger.warning("secret 'flatfinder-secrets' missing (%r); running without it", e)
        secrets = []

    @app.function(image=image, schedule=modal.Period(hours=1), secrets=secrets, timeout=600)
    def scan():
        """Runs unattended on a schedule: pull -> enrich -> match -> draft."""
        os.environ["FLATFINDER_STORE"] = "modal"
        return run_scan_cycle()

    @app.function(image=image, secrets=secrets, timeout=600)
    def trigger():
        """On-demand scan: `modal run app_modal.py::trigger`."""
        os.environ["FLATFINDER_STORE"] = "modal"
        return run_scan_cycle()

    @app.function(image=image, secrets=secrets)
    def seed_brief(text: str = "", brief_id: str = "brief-demo"):
        """Drop a brief into the shared store: `modal run app_modal.py::seed_brief`."""
        os.environ["FLATFINDER_STORE"] = "modal"
        return seed_brief_cycle(text=text or None, brief_id=brief_id)

    @app.function(image=image, secrets=secrets)
    def submit(brief_id: str, listing_id: str):
        """On-demand: register interest / request a viewing for one match."""
        os.environ["FLATFINDER_STORE"] = "modal"
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
        os.environ["FLATFINDER_STORE"] = "modal"
        os.environ.setdefault("FLATFINDER_TEMPLATE_DIR", "/assets/web_templates")
        from web.app import create_app
        return create_app()

    @app.local_entrypoint()
    def main(seed: bool = False, text: str = ""):
        """Manual driver: `modal run app_modal.py` runs one scan on demand.

        Add `--seed --text "1 bed Hackney up to £2500, must have lift"` to seed a
        brief into the shared store before scanning.
        """
        if seed:
            print(json.dumps(seed_brief.remote(text=text), default=str))
        print(json.dumps(scan.remote(), default=str))
