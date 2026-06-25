"""PayPal (sandbox by default) — create + capture a one-off order so the agent's
service can actually take money. Subscriptions follow the same token pattern.

Set PAYPAL_CLIENT_ID / PAYPAL_SECRET (sandbox creds from developer.paypal.com).
Without them, create_order returns a simulated order so the demo still flows.
"""
import uuid

from flatfinder.config import (PAYPAL_BASE, PAYPAL_CLIENT_ID, PAYPAL_SECRET,
                               has_paypal)
from flatfinder.http import post_form, post_json


def _token() -> str:
    data = post_form(f"{PAYPAL_BASE}/v1/oauth2/token",
                     {"grant_type": "client_credentials"},
                     auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET))
    return data["access_token"]


def create_order(amount: str = "9.99", currency: str = "GBP", description: str = "Flat-finder Pro") -> dict:
    if not has_paypal():
        # simulated order for offline demo
        oid = "SIM-" + uuid.uuid4().hex[:12]
        return {"id": oid, "status": "CREATED", "simulated": True,
                "approve_url": f"https://sandbox.paypal.com/checkoutnow?token={oid}",
                "amount": amount}
    tok = _token()
    order = post_json(
        f"{PAYPAL_BASE}/v2/checkout/orders",
        {"intent": "CAPTURE",
         "purchase_units": [{"amount": {"currency_code": currency, "value": amount},
                             "description": description}]},
        headers={"Authorization": f"Bearer {tok}"})
    approve = next((lk["href"] for lk in order.get("links", []) if lk["rel"] == "approve"), "")
    return {"id": order["id"], "status": order["status"], "approve_url": approve, "amount": amount}


def capture_order(order_id: str) -> dict:
    if not has_paypal() or order_id.startswith("SIM-"):
        return {"id": order_id, "status": "COMPLETED", "simulated": True}
    tok = _token()
    return post_json(f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture", {},
                     headers={"Authorization": f"Bearer {tok}"})
