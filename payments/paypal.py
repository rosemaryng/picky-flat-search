"""PayPal (sandbox by default) — take real money for the agent's Pro service.

Two checkout shapes are supported, both with an offline-simulated fallback so the
demo flows with **zero keys**:

- **One-off order** (`create_order` -> approve -> `capture_order`): a single
  £9.99 Pro unlock. Money is only real once the capture comes back
  ``status == "COMPLETED"`` — see :func:`is_completed`.
- **Subscription** (`create_subscription` -> approve -> `get_subscription`): a
  recurring Pro plan. It only counts once the subscription is ``ACTIVE`` — see
  :func:`is_active`.

Set ``PAYPAL_CLIENT_ID`` / ``PAYPAL_SECRET`` (sandbox creds from
developer.paypal.com) to hit the live sandbox. Without them every call returns a
deterministic simulated object so the dashboard still demonstrates "made money".

The golden rule the dashboard relies on: **revenue is recorded only when the
capture/subscription has actually settled** (COMPLETED / ACTIVE). Use the
:func:`is_completed` / :func:`is_active` predicates rather than re-checking the
raw status string at each call site.
"""
import uuid

from flatfinder.config import (PAYPAL_BASE, PAYPAL_CLIENT_ID, PAYPAL_SECRET,
                               has_paypal)
from flatfinder.http import get_json, post_form, post_json

# Pro plan defaults (kept here so the price lives in one place).
PRO_PRICE = "9.99"
PRO_CURRENCY = "GBP"
PRO_DESCRIPTION = "Flat-finder Pro"

# Settled states that mean we actually got paid.
_COMPLETED = "COMPLETED"
_ACTIVE = "ACTIVE"


def _token() -> str:
    """Fetch an OAuth2 access token for the sandbox/live REST API."""
    data = post_form(f"{PAYPAL_BASE}/v1/oauth2/token",
                     {"grant_type": "client_credentials"},
                     auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET))
    return data["access_token"]


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _approve_link(obj: dict) -> str:
    """Pull the buyer-facing approval URL out of a PayPal links array."""
    for link in obj.get("links", []):
        if link.get("rel") in ("approve", "payer-action"):
            return link.get("href", "")
    return ""


# --------------------------------------------------------------------------- #
# One-off order
# --------------------------------------------------------------------------- #
def create_order(amount: str = PRO_PRICE, currency: str = PRO_CURRENCY,
                 description: str = PRO_DESCRIPTION) -> dict:
    """Create a one-off CAPTURE order. Returns id/status/approve_url/amount.

    With no PayPal keys this returns a simulated ``SIM-…`` order so the offline
    demo still has something to approve and capture.
    """
    if not has_paypal():
        oid = "SIM-" + uuid.uuid4().hex[:12]
        return {"id": oid, "status": "CREATED", "simulated": True,
                "approve_url": f"https://sandbox.paypal.com/checkoutnow?token={oid}",
                "amount": amount}
    order = post_json(
        f"{PAYPAL_BASE}/v2/checkout/orders",
        {"intent": "CAPTURE",
         "purchase_units": [{"amount": {"currency_code": currency, "value": amount},
                             "description": description}]},
        headers=_auth_headers())
    return {"id": order["id"], "status": order.get("status", "CREATED"),
            "approve_url": _approve_link(order), "amount": amount}


def capture_order(order_id: str) -> dict:
    """Capture an approved order. Simulated orders settle as COMPLETED."""
    if not has_paypal() or order_id.startswith("SIM-"):
        return {"id": order_id, "status": _COMPLETED, "simulated": True}
    return post_json(f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture", {},
                     headers=_auth_headers())


# --------------------------------------------------------------------------- #
# Subscription (recurring Pro)
# --------------------------------------------------------------------------- #
def create_subscription(plan_id: str = "", description: str = PRO_DESCRIPTION + " (monthly)") -> dict:
    """Start a subscription against an existing billing ``plan_id``.

    Returns id/status/approve_url/amount. With no keys (or no plan id) this
    returns a simulated ``SIMSUB-…`` subscription so the demo can show a
    recurring flow without a configured plan.
    """
    if not has_paypal() or not plan_id:
        sid = "SIMSUB-" + uuid.uuid4().hex[:12]
        return {"id": sid, "status": "APPROVAL_PENDING", "simulated": True,
                "approve_url": f"https://sandbox.paypal.com/webapps/billing/subscriptions?ba_token={sid}",
                "amount": PRO_PRICE}
    sub = post_json(
        f"{PAYPAL_BASE}/v1/billing/subscriptions",
        {"plan_id": plan_id, "custom_id": description},
        headers=_auth_headers())
    return {"id": sub["id"], "status": sub.get("status", "APPROVAL_PENDING"),
            "approve_url": _approve_link(sub), "amount": PRO_PRICE}


def get_subscription(subscription_id: str) -> dict:
    """Fetch a subscription's current state (used to confirm it went ACTIVE)."""
    if not has_paypal() or subscription_id.startswith("SIMSUB-"):
        return {"id": subscription_id, "status": _ACTIVE, "simulated": True}
    return get_json(f"{PAYPAL_BASE}/v1/billing/subscriptions/{subscription_id}",
                    headers=_auth_headers())


# --------------------------------------------------------------------------- #
# Settlement predicates — the single source of truth for "did we get paid?"
# --------------------------------------------------------------------------- #
def is_completed(capture: dict) -> bool:
    """True only when a captured order has settled (``status == COMPLETED``)."""
    return str(capture.get("status", "")).upper() == _COMPLETED


def is_active(subscription: dict) -> bool:
    """True only when a subscription has settled (``status == ACTIVE``)."""
    return str(subscription.get("status", "")).upper() == _ACTIVE
