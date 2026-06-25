"""Offline tests for the Modal deployment glue (app_modal.py).

These never require a real Modal account: `app_modal` is import-safe without the
`modal` package, and the pure helpers run against a `LocalStore`. If importing
the module fails for an unexpected reason (e.g. a half-installed/un-authed Modal
in some envs), the whole module skips gracefully instead of failing the suite.
"""
import json

import pytest

try:
    import app_modal
except Exception as e:  # pragma: no cover - defensive: never fail on Modal setup
    pytest.skip(f"app_modal import unavailable: {e!r}", allow_module_level=True)

from flatfinder.models import Brief, Listing, Match
from flatfinder.store import LocalStore


def test_module_imports_without_modal_account():
    """The deployment module imports offline and exposes its helpers."""
    for name in ("scan_report", "briefs_from_rows", "matches_payload",
                 "run_scan_cycle", "seed_brief_cycle"):
        assert callable(getattr(app_modal, name))


def test_scan_report_counts_new_listings():
    report = app_modal.scan_report(n_briefs=2, listings_before=5,
                                   listings_after=8, n_matches=3)
    assert report == {"briefs": 2, "listings": 8, "new": 3, "matches": 3}
    # report must be JSON-serialisable for structured logging
    assert json.loads(json.dumps(report)) == report


def test_scan_report_never_negative_new():
    """A shrinking store (e.g. eviction) must not produce a negative 'new'."""
    assert app_modal.scan_report(1, 10, 4, 0)["new"] == 0


def test_matches_payload_shape():
    listing = Listing(id="l1", source="t", url="http://x/1", address="1 Test St")
    match = Match(brief_id="b1", listing=listing, score=72.5, reasons=["close"])
    assert app_modal.matches_payload([match]) == [
        {"score": 72.5, "address": "1 Test St", "url": "http://x/1"}
    ]


def test_briefs_from_rows_filters_unknown_keys_and_blanks():
    rows = [
        {"id": "b1", "text": "1 bed Hackney", "min_beds": 1, "bogus": "drop me"},
        {"text": "no id -> skipped"},
        "not-a-dict",
    ]
    briefs = app_modal.briefs_from_rows(rows)
    assert [b.id for b in briefs] == ["b1"]
    assert isinstance(briefs[0], Brief)
    assert briefs[0].min_beds == 1


def test_briefs_from_rows_falls_back_to_demo():
    briefs = app_modal.briefs_from_rows([])
    assert len(briefs) == 1
    assert isinstance(briefs[0], Brief)


def test_set_status_writes_heartbeat(tmp_path):
    store = LocalStore(path=str(tmp_path / "db.json"))
    app_modal._set_status(store, "running", started_at=123)
    assert store.agents()["scan"]["status"] == "running"
    assert store.agents()["scan"]["started_at"] == 123


def test_set_status_tolerates_broken_store():
    """A missing/read-only store must not crash the scan loop."""
    class Broken:
        def set_agent_status(self, *a, **k):
            raise RuntimeError("no shared dict")

    app_modal._set_status(Broken(), "running")  # should swallow and log


def test_listing_count_handles_missing_stats():
    class NoStats:
        def stats(self):
            raise RuntimeError("unsupported")

    assert app_modal._listing_count(NoStats()) == 0


def test_run_scan_cycle_offline_with_local_store(tmp_path, monkeypatch):
    """Drive the full cycle with a fake matcher so it stays offline + deterministic."""
    store = LocalStore(path=str(tmp_path / "db.json"))
    listing = Listing(id="l9", source="t", url="http://x/9", address="9 Demo Rd")
    match = Match(brief_id="brief-demo", listing=listing, score=88.0)

    def fake_run_scan(briefs, store=None, **kw):
        store.upsert_listing(listing.to_dict())
        store.add_match(match.to_dict())
        return [match]

    monkeypatch.setattr("flatfinder.pipeline.run_scan", fake_run_scan)
    payload = app_modal.run_scan_cycle(store=store)

    assert payload == [{"score": 88.0, "address": "9 Demo Rd", "url": "http://x/9"}]
    agent = store.agents()["scan"]
    assert agent["status"] == "idle"
    assert agent["last_matches"] == 1
    assert agent["last_listings"] == 1


def test_seed_brief_cycle_writes_to_shared_store(tmp_path):
    store = LocalStore(path=str(tmp_path / "db.json"))
    out = app_modal.seed_brief_cycle(
        text="1 bed Hackney up to £2000, must have lift",
        brief_id="brief-test", store=store,
    )
    assert out["id"] == "brief-test"
    # a second handle (another agent) sees the seeded brief in shared state
    other = LocalStore(path=str(tmp_path / "db.json"))
    assert [b["id"] for b in other.briefs()] == ["brief-test"]
