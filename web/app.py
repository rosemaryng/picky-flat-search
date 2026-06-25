"""Flask dashboard: ranked shortlist + enquiry drafts + agent heartbeat, plus a
PayPal checkout that records revenue (the demo's 'made money' proof).

    python -m web.app           # http://localhost:5000

Runs with zero keys: the LOCAL JSON store backs it and PayPal is simulated, so
the dashboard renders and "earns" without any external service configured.

Revenue invariant: a payment is only ever stored as ``status="paid"`` once the
PayPal capture is COMPLETED (one-off) or the subscription is ACTIVE. Everything
else is recorded with its raw status and is excluded from revenue totals.
"""
import os
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for

from flatfinder.store import get_store
from payments import paypal

# Rough per-item time the agent saves a human (minutes). Used only for the
# "hours saved" headline stat — a motivational estimate, not an exact figure.
_MIN_PER_LISTING = 4      # skimming + filtering a listing the agent triaged
_MIN_PER_MATCH = 12       # researching a shortlisted flat + writing an enquiry


def _hours_saved(stats: dict) -> float:
    minutes = (stats.get("listings", 0) * _MIN_PER_LISTING
               + stats.get("matches", 0) * _MIN_PER_MATCH)
    return round(minutes / 60.0, 1)


def _heartbeat(store) -> dict:
    """Most-recent agent activity, with a human 'last seen' string."""
    agents = store.agents()
    last_ts = max((a.get("ts", 0) for a in agents.values()), default=0)
    return {
        "agents": agents,
        "count": len(agents),
        "last_ts": last_ts,
        "last_seen": _ago(last_ts) if last_ts else "never",
        "alive": bool(last_ts) and (time.time() - last_ts) < 3600,
    }


def _ago(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _record_paid(store, payment_id: str, settled: bool, amount: float, raw: dict):
    """Persist a payment, marking it 'paid' only when actually settled."""
    status = "paid" if settled else (raw.get("status", "unknown") if raw else "unknown")
    store.record_payment({"id": payment_id, "amount": amount, "status": status,
                          "raw": raw})
    return status


# Walkability controls shown in the search form. Each maps a POI to a brief
# keyword the scorer understands. Form values: "" (no pref) / "must5" / "must10"
# / "nice".
_WALK_FIELDS = {
    "gym": ("Gym", "gym"),
    "groceries": ("Groceries", "groceries"),
    "tube": ("Tube / station", "near the tube"),
}
# Feature checkboxes: form field -> (label, brief keyword).
_FEATURE_FIELDS = {
    "period": ("Period conversion", "period"),
    "high_ceilings": ("High ceilings", "high ceilings"),
    "natural_light": ("Natural light", "natural light"),
    "south_facing": ("South-facing", "south facing"),
    "garden": ("Garden", "garden"),
    "balcony": ("Balcony", "balcony"),
}


def _int_or_none(raw: str):
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _brief_from_form(form) -> "object":
    """Turn the dashboard search form (free text + structured picks) into a Brief.

    The free text is parsed first (LLM or deterministic), then the structured
    selections are merged in so the scorer gets explicit must/nice keywords and
    the free text records the distances a user chose.
    """
    from flatfinder.brief import parse

    text = (form.get("brief_text") or "").strip()
    extra_sentences: list[str] = []
    must: list[str] = []
    nice: list[str] = []

    for field_name, (label, keyword) in _WALK_FIELDS.items():
        choice = form.get(f"walk_{field_name}", "")
        if choice == "must5":
            must.append(keyword)
            extra_sentences.append(f"Must have {label.lower()} within 5 mins walk.")
        elif choice == "must10":
            must.append(keyword)
            extra_sentences.append(f"Must have {label.lower()} within 10 mins walk.")
        elif choice == "nice":
            nice.append(keyword)
            extra_sentences.append(f"Nice to have {label.lower()} nearby.")

    for field_name, (label, keyword) in _FEATURE_FIELDS.items():
        choice = form.get(f"feat_{field_name}", "")
        if choice == "must":
            must.append(keyword)
            extra_sentences.append(f"Must have {label.lower()}.")
        elif choice == "nice":
            nice.append(keyword)
            extra_sentences.append(f"Nice to have {label.lower()}.")

    full_text = " ".join(filter(None, [text] + extra_sentences)).strip()
    brief = parse(full_text or "A nice London flat", id="brief-user")

    # structured overrides win over whatever the parser guessed
    max_price = _int_or_none(form.get("max_price"))
    if max_price is not None:
        brief.max_price = max_price
    min_beds = _int_or_none(form.get("min_beds"))
    if min_beds is not None:
        brief.min_beds = min_beds
    areas = [a.strip() for a in (form.get("areas") or "").split(",") if a.strip()]
    if areas:
        brief.areas = areas

    # merge keywords without duplicates, preserving the parser's findings
    brief.must_have = list(dict.fromkeys(brief.must_have + must))
    brief.nice_to_have = list(dict.fromkeys(
        [n for n in brief.nice_to_have if n not in brief.must_have]
        + [n for n in nice if n not in brief.must_have]))
    return brief


def _current_brief(store) -> dict | None:
    """The user's saved search brief, if any (prefers the dashboard-entered one)."""
    rows = store.briefs()
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
    return by_id.get("brief-user") or (rows[0] if rows else None)


def create_app() -> Flask:
    template_dir = os.environ.get("FLATFINDER_TEMPLATE_DIR")
    app = Flask(__name__, template_folder=template_dir) if template_dir else Flask(__name__)

    @app.route("/")
    def index():
        store = get_store()
        matches = store.matches(min_score=0)[:50]
        stats = store.stats()
        return render_template("index.html", matches=matches, stats=stats,
                               hours_saved=_hours_saved(stats),
                               heartbeat=_heartbeat(store),
                               brief=_current_brief(store),
                               pro_price=paypal.PRO_PRICE)

    @app.route("/api/matches")
    def api_matches():
        return jsonify(get_store().matches(min_score=0))

    @app.route("/upgrade", methods=["POST"])
    def upgrade():
        """Kick off a Pro checkout. ?plan=subscription for recurring, else one-off."""
        plan = request.values.get("plan", "oneoff")
        if plan == "subscription":
            order = paypal.create_subscription()
        else:
            order = paypal.create_order(amount=paypal.PRO_PRICE,
                                        description=paypal.PRO_DESCRIPTION)
        return redirect(order.get("approve_url") or url_for("index"))

    @app.route("/paypal/return")
    def paypal_return():
        """PayPal redirects here after approval. Capture/confirm, then record
        revenue **only** when the money has truly settled."""
        store = get_store()
        amount = float(paypal.PRO_PRICE)
        sub_id = request.args.get("subscription_id", "")
        token = request.args.get("token") or request.args.get("order_id", "")
        if sub_id:
            sub = paypal.get_subscription(sub_id)
            _record_paid(store, sub_id, paypal.is_active(sub), amount, sub)
        elif token:
            cap = paypal.capture_order(token)
            _record_paid(store, token, paypal.is_completed(cap), amount, cap)
        return redirect(url_for("index"))

    @app.route("/simulate-payment", methods=["POST"])
    def simulate_payment():
        """Demo helper: run the full create->capture flow inline (simulated when
        no keys) and record revenue only if the capture COMPLETED."""
        store = get_store()
        order = paypal.create_order(amount=paypal.PRO_PRICE)
        cap = paypal.capture_order(order["id"])
        _record_paid(store, order["id"], paypal.is_completed(cap),
                     float(paypal.PRO_PRICE), cap)
        return redirect(url_for("index"))

    @app.route("/approve-send", methods=["POST"])
    def approve_send():
        """Human-in-the-loop: approve a drafted enquiry so the agent sends it.

        Flips the match's status to 'sent' (upsert by brief_id::listing_id).
        """
        brief_id = request.values.get("brief_id", "")
        listing_id = request.values.get("listing_id", "")
        store = get_store()
        for m in store.matches(min_score=0):
            if m.get("brief_id") == brief_id and m.get("listing", {}).get("id") == listing_id:
                m["status"] = "sent"
                store.add_match(m)
                break
        return redirect(url_for("index"))

    @app.route("/api/trigger", methods=["POST"])
    def api_trigger():
        """Kick a fresh scan. Prefers the deployed Modal `trigger` function and
        falls back to running a scan cycle in a background thread for local dev.
        Optimistically flips the 'scan' agent to 'running' so the dashboard shows
        activity immediately. Never 500s — failures are returned as JSON."""
        try:
            get_store().set_agent_status("scan", "running", started_at=time.time())
            try:
                import modal
                modal.Function.from_name("flat-finder", "trigger").spawn()
                mode = "modal"
            except Exception:
                import app_modal
                threading.Thread(target=app_modal.run_scan_cycle,
                                 daemon=True).start()
                mode = "local"
            return jsonify({"ok": True, "mode": mode})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/search", methods=["POST"])
    def api_search():
        """Save the user's search brief (free text + structured picks) and kick a
        fresh scan that ranks listings against it. Never 500s."""
        try:
            store = get_store()
            brief = _brief_from_form(request.form)
            store.upsert_brief(brief.to_dict())
            store.set_agent_status("scan", "running", started_at=time.time())
            try:
                import modal
                modal.Function.from_name("flat-finder", "trigger").spawn()
                mode = "modal"
            except Exception:
                import app_modal
                threading.Thread(target=app_modal.run_scan_cycle,
                                 daemon=True).start()
                mode = "local"
            return jsonify({"ok": True, "mode": mode, "brief_id": brief.id,
                            "must_have": brief.must_have,
                            "nice_to_have": brief.nice_to_have})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/seed-demo", methods=["POST"])
    def api_seed_demo():
        """Populate the store with the pre-scored demo matches for a guaranteed
        demo, returning how many were written."""
        from app_modal import seed_demo_data
        produced = seed_demo_data(get_store())
        return jsonify({"ok": True, "count": len(produced)})

    @app.route("/api/status")
    def api_status():
        """Dashboard poll target: current scan heartbeat, store stats, and the
        number of matches available."""
        store = get_store()
        return jsonify({
            "scan": store.agents().get("scan"),
            "stats": store.stats(),
            "matches": len(store.matches(min_score=0)),
        })

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
