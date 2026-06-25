"""Payments + dashboard tests — no network, no PayPal keys required.

Covers:
- the PayPal helper (`payments.paypal`) with HTTP mocked out, and its simulated
  fallback when no keys are configured;
- the settlement invariant: revenue is only ever counted for COMPLETED orders /
  ACTIVE subscriptions ("paid"); and
- the Flask dashboard via a test client, backed by an isolated LOCAL store.
"""
import pytest

from flatfinder import store as store_mod
from payments import paypal


# --------------------------------------------------------------------------- #
# Fixtures: a fresh LocalStore on a temp DB, shared with the Flask app.
# --------------------------------------------------------------------------- #
@pytest.fixture
def local_store(tmp_path):
    """An isolated LocalStore on a temp JSON file."""
    return store_mod.LocalStore(path=str(tmp_path / "db.json"))


@pytest.fixture
def client(local_store, monkeypatch):
    from web import app as web_app

    # The app calls the module-global get_store(); make it return our store so
    # the test and the app share the exact same instance.
    monkeypatch.setattr(web_app, "get_store", lambda: local_store)
    application = web_app.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture
def no_paypal(monkeypatch):
    """Force the 'no keys' simulated path regardless of the host env."""
    monkeypatch.setattr(paypal, "has_paypal", lambda: False)


@pytest.fixture
def with_paypal(monkeypatch):
    """Pretend keys are present so the real REST branches are exercised."""
    monkeypatch.setattr(paypal, "has_paypal", lambda: True)
    monkeypatch.setattr(paypal, "_token", lambda: "tok-123")


# --------------------------------------------------------------------------- #
# PayPal helper — simulated fallback (zero keys)
# --------------------------------------------------------------------------- #
def test_create_order_simulated_when_no_keys(no_paypal):
    order = paypal.create_order()
    assert order["simulated"] is True
    assert order["id"].startswith("SIM-")
    assert order["amount"] == paypal.PRO_PRICE
    assert order["approve_url"]


def test_capture_order_simulated_is_completed(no_paypal):
    cap = paypal.capture_order("SIM-abc123")
    assert paypal.is_completed(cap)
    assert cap["status"] == "COMPLETED"


def test_capture_sim_order_completed_even_with_keys(with_paypal):
    # A SIM- order id always settles as COMPLETED, even if keys are present.
    assert paypal.is_completed(paypal.capture_order("SIM-xyz"))


def test_subscription_simulated_flow(no_paypal):
    sub = paypal.create_subscription()
    assert sub["simulated"] is True
    assert sub["id"].startswith("SIMSUB-")
    confirmed = paypal.get_subscription(sub["id"])
    assert paypal.is_active(confirmed)


# --------------------------------------------------------------------------- #
# PayPal helper — real REST path with HTTP mocked
# --------------------------------------------------------------------------- #
def test_token_posts_client_credentials(monkeypatch):
    seen = {}

    def fake_post_form(url, data, headers=None, auth=None, timeout=30):
        seen["url"] = url
        seen["grant"] = data["grant_type"]
        seen["auth"] = auth
        return {"access_token": "abc"}

    monkeypatch.setattr(paypal, "post_form", fake_post_form)
    assert paypal._token() == "abc"
    assert seen["url"].endswith("/v1/oauth2/token")
    assert seen["grant"] == "client_credentials"


def test_create_order_calls_paypal_api(with_paypal, monkeypatch):
    captured = {}

    def fake_post_json(url, payload, headers=None, timeout=30):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {"id": "ORDER-1", "status": "CREATED",
                "links": [{"rel": "approve",
                           "href": "https://approve.example/ORDER-1"}]}

    monkeypatch.setattr(paypal, "post_json", fake_post_json)

    order = paypal.create_order(amount="9.99", description="Flat-finder Pro")
    assert order["id"] == "ORDER-1"
    assert order["approve_url"] == "https://approve.example/ORDER-1"
    assert "/v2/checkout/orders" in captured["url"]
    assert captured["payload"]["intent"] == "CAPTURE"
    assert captured["headers"]["Authorization"] == "Bearer tok-123"


def test_capture_order_calls_paypal_api(with_paypal, monkeypatch):
    def fake_post_json(url, payload, headers=None, timeout=30):
        assert url.endswith("/ORDER-1/capture")
        return {"id": "ORDER-1", "status": "COMPLETED"}

    monkeypatch.setattr(paypal, "post_json", fake_post_json)
    assert paypal.is_completed(paypal.capture_order("ORDER-1"))


def test_create_subscription_calls_paypal_api(with_paypal, monkeypatch):
    def fake_post_json(url, payload, headers=None, timeout=30):
        assert url.endswith("/v1/billing/subscriptions")
        assert payload["plan_id"] == "P-123"
        return {"id": "SUB-9", "status": "APPROVAL_PENDING",
                "links": [{"rel": "approve", "href": "https://approve.example/SUB-9"}]}

    monkeypatch.setattr(paypal, "post_json", fake_post_json)
    sub = paypal.create_subscription(plan_id="P-123")
    assert sub["id"] == "SUB-9"
    assert sub["approve_url"] == "https://approve.example/SUB-9"


def test_is_completed_and_is_active_predicates():
    assert paypal.is_completed({"status": "COMPLETED"})
    assert paypal.is_completed({"status": "completed"})  # case-insensitive
    assert not paypal.is_completed({"status": "PENDING"})
    assert not paypal.is_completed({})
    assert paypal.is_active({"status": "ACTIVE"})
    assert not paypal.is_active({"status": "APPROVAL_PENDING"})


# --------------------------------------------------------------------------- #
# Revenue invariant on the store: only "paid" counts.
# --------------------------------------------------------------------------- #
def test_revenue_only_counts_paid(local_store):
    local_store.record_payment({"id": "p1", "amount": 9.99, "status": "paid"})
    local_store.record_payment({"id": "p2", "amount": 9.99, "status": "PENDING"})
    local_store.record_payment({"id": "p3", "amount": 9.99, "status": "unknown"})
    assert local_store.revenue() == 9.99


# --------------------------------------------------------------------------- #
# Flask dashboard (LOCAL store, zero keys)
# --------------------------------------------------------------------------- #
def test_index_returns_200_with_empty_local_store(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Chirpie" in body
    assert "hours saved" in body


def test_api_matches_returns_json(client):
    resp = client.get("/api/matches")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_simulate_payment_records_revenue_when_completed(client, local_store, no_paypal):
    assert local_store.revenue() == 0.0
    resp = client.post("/simulate-payment")
    assert resp.status_code == 302  # redirect back to /
    assert local_store.revenue() == float(paypal.PRO_PRICE)


def test_paypal_return_does_not_count_unsettled_capture(client, local_store, monkeypatch):
    # capture comes back not-COMPLETED -> must NOT be counted as revenue
    monkeypatch.setattr(paypal, "capture_order",
                        lambda oid: {"id": oid, "status": "PENDING"})
    resp = client.get("/paypal/return?token=ORDER-X")
    assert resp.status_code == 302
    assert local_store.revenue() == 0.0


def test_paypal_return_counts_completed_capture(client, local_store, monkeypatch):
    monkeypatch.setattr(paypal, "capture_order",
                        lambda oid: {"id": oid, "status": "COMPLETED"})
    client.get("/paypal/return?token=ORDER-Y")
    assert local_store.revenue() == float(paypal.PRO_PRICE)


def test_paypal_return_counts_active_subscription(client, local_store, monkeypatch):
    monkeypatch.setattr(paypal, "get_subscription",
                        lambda sid: {"id": sid, "status": "ACTIVE"})
    client.get("/paypal/return?subscription_id=SUB-1")
    assert local_store.revenue() == float(paypal.PRO_PRICE)


def test_paypal_return_does_not_count_pending_subscription(client, local_store, monkeypatch):
    monkeypatch.setattr(paypal, "get_subscription",
                        lambda sid: {"id": sid, "status": "APPROVAL_PENDING"})
    client.get("/paypal/return?subscription_id=SUB-2")
    assert local_store.revenue() == 0.0


@pytest.fixture
def no_scan(monkeypatch):
    """Force the local scan path and stub it out so /api/search never spawns
    a real Modal job or scrapes during tests."""
    import app_modal
    try:
        import modal
        monkeypatch.setattr(modal.Function, "from_name",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no modal")))
    except Exception:
        pass
    monkeypatch.setattr(app_modal, "run_scan_cycle", lambda *a, **k: [])


def test_search_form_rendered_on_index(client):
    body = client.get("/").get_data(as_text=True)
    assert "Tell Chirpie what you're looking for" in body
    assert 'name="walk_gym"' in body and 'name="feat_period"' in body


def test_api_search_saves_brief_from_structured_form(client, local_store, no_scan):
    resp = client.post("/api/search", data={
        "brief_text": "A bright period flat in Hackney with high ceilings",
        "areas": "Hackney, Dalston", "max_price": "2500", "min_beds": "1",
        "walk_gym": "must5", "walk_groceries": "must10", "walk_tube": "nice",
        "feat_period": "must", "feat_high_ceilings": "must",
        "feat_natural_light": "nice",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    brief = next(b for b in local_store.briefs() if b["id"] == "brief-user")
    assert brief["max_price"] == 2500 and brief["min_beds"] == 1
    assert brief["areas"] == ["Hackney", "Dalston"]
    for kw in ("gym", "groceries", "period", "high ceilings"):
        assert kw in brief["must_have"]
    assert "natural light" in brief["nice_to_have"]


def test_api_search_works_with_only_free_text(client, local_store, no_scan):
    resp = client.post("/api/search", data={"brief_text": "anywhere central, £2000"})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert any(b["id"] == "brief-user" for b in local_store.briefs())


def test_approve_send_marks_match_sent(client, local_store):
    match = {"brief_id": "b1", "score": 80, "reasons": [], "enquiry_draft": "hi",
             "status": "drafted",
             "listing": {"id": "L1", "address": "1 Test St", "price": 2000,
                         "url": "http://x"}}
    local_store.add_match(match)
    resp = client.post("/approve-send", data={"brief_id": "b1", "listing_id": "L1"})
    assert resp.status_code == 302
    sent = [m for m in local_store.matches(min_score=0)
            if m["listing"]["id"] == "L1"][0]
    assert sent["status"] == "sent"
