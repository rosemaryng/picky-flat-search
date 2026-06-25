"""Tiny Flask dashboard: shows the ranked shortlist, enquiry drafts, and a
PayPal 'upgrade' button that records revenue (the demo's 'made money' proof).

    python -m web.app           # http://localhost:5000
"""
from flask import Flask, jsonify, redirect, render_template, request

from flatfinder.store import get_store
from payments import paypal


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        store = get_store()
        matches = store.matches(min_score=0)[:50]
        return render_template("index.html", matches=matches, stats=store.stats())

    @app.route("/api/matches")
    def api_matches():
        return jsonify(get_store().matches(min_score=0))

    @app.route("/upgrade", methods=["POST"])
    def upgrade():
        order = paypal.create_order(amount="9.99", description="Flat-finder Pro")
        return redirect(order.get("approve_url") or "/")

    @app.route("/paypal/return")
    def paypal_return():
        token = request.args.get("token") or request.args.get("order_id", "")
        store = get_store()
        if token:
            cap = paypal.capture_order(token)
            store.record_payment({"id": token, "amount": 9.99, "status": "paid",
                                  "raw": cap})
        return redirect("/")

    @app.route("/simulate-payment", methods=["POST"])
    def simulate_payment():
        """Demo helper: record a paid order without leaving the page."""
        order = paypal.create_order(amount="9.99")
        paypal.capture_order(order["id"])
        get_store().record_payment({"id": order["id"], "amount": 9.99, "status": "paid"})
        return redirect("/")

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
