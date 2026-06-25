"""Offline unit tests for the Supabase store backend.

No network, no keys: a fake `supabase` module is injected into ``sys.modules`` and
``create_client`` is monkeypatched to return an in-memory fake client that records
every upsert. This lets us assert that SupabaseStore only ever writes columns that
exist in ``supabase_schema.sql`` (no unknown-column 400s), that nested listings
round-trip through ``matches``, and that the coordination methods work.
"""
import re
import sys
import types
from pathlib import Path

import pytest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "supabase_schema.sql"


# --- parse the real schema so the tests track it automatically ---------------
def _schema_columns() -> dict[str, set[str]]:
    """Map table name -> set of column names declared in supabase_schema.sql."""
    sql = SCHEMA_PATH.read_text()
    tables: dict[str, set[str]] = {}
    for m in re.finditer(
        r"create table if not exists\s+(\w+)\s*\((.*?)\);", sql,
        re.IGNORECASE | re.DOTALL,
    ):
        name, body = m.group(1), m.group(2)
        cols: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            tok = line.split()[0]
            if tok.lower() in {"primary", "constraint", "unique", "foreign", "check"}:
                continue
            cols.add(tok)
        tables[name] = cols
    return tables


SCHEMA = _schema_columns()

# primary key per table (matches supabase_schema.sql)
_PKS = {
    "briefs": "id", "listings": "id", "matches": "id", "viewings": "id",
    "payments": "id", "agents": "name", "notes": "key", "enrichment_cache": "key",
}


# --- in-memory fake Supabase client ------------------------------------------
class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Table:
    def __init__(self, name):
        self.name = name
        self.pk = _PKS.get(name, "id")
        self.rows: dict = {}
        self.upserts: list[dict] = []  # every row written, for assertions


class _Query:
    def __init__(self, table):
        self.t = table
        self._filters: list[tuple] = []
        self._order = None
        self._count = None
        self._upsert = None

    def select(self, _cols="*", count=None):
        self._count = count
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def upsert(self, row):
        self._upsert = row
        return self

    def execute(self):
        if self._upsert is not None:
            row = dict(self._upsert)
            self.t.upserts.append(row)
            self.t.rows[row[self.t.pk]] = row
            return _Result([row])
        rows = list(self.t.rows.values())
        for op, col, val in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif op == "gte":
                rows = [r for r in rows if (r.get(col) or 0) >= val]
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: (r.get(col) or 0), reverse=desc)
        count = len(rows) if self._count else None
        return _Result(rows, count=count)


class FakeClient:
    def __init__(self):
        self.tables: dict[str, _Table] = {}

    def table(self, name):
        t = self.tables.setdefault(name, _Table(name))
        return _Query(t)


@pytest.fixture()
def store(monkeypatch):
    """A SupabaseStore wired to the in-memory FakeClient (no network/keys)."""
    fake_client = FakeClient()
    fake_mod = types.ModuleType("supabase")
    fake_mod.create_client = lambda url, key: fake_client
    monkeypatch.setitem(sys.modules, "supabase", fake_mod)

    from flatfinder.store import SupabaseStore
    s = SupabaseStore()
    return s, fake_client


def _assert_columns(table: _Table):
    """Every column written must exist in the schema for that table."""
    allowed = SCHEMA[table.name]
    for row in table.upserts:
        unknown = set(row) - allowed
        assert not unknown, f"{table.name}: unknown columns {unknown} (allowed {allowed})"


# --- tests -------------------------------------------------------------------
def test_enrichment_cache_table_in_schema():
    assert "enrichment_cache" in SCHEMA
    assert {"key", "kind", "value", "updated_at"} <= SCHEMA["enrichment_cache"]


def test_upsert_listing_filters_unknown_columns(store):
    s, fake = store
    listing = {
        "id": "L1", "source": "rightmove", "url": "http://x", "price": 2000,
        "beds": 2, "baths": 1, "address": "Hackney", "postcode": "E9 5JX",
        "summary": "bright flat", "epc": "B", "sqm": 55,
        # fields that are NOT schema columns and would cause a 400 if passed raw:
        "property_type": "flat", "lat": 51.5, "lng": -0.05,
        "pois": {"gym": 3}, "transport": {"walk_min": 4}, "raw": {"foo": "bar"},
    }
    s.upsert_listing(listing)

    t = fake.tables["listings"]
    _assert_columns(t)
    row = t.upserts[0]
    # the full listing (incl. non-schema fields) is preserved in the jsonb `data`
    assert row["data"] == listing
    assert row["data"]["pois"] == {"gym": 3}


def test_upsert_brief_filters_unknown_columns(store):
    s, fake = store
    brief = {
        "id": "B1", "text": "2 bed Hackney", "max_price": 2500, "min_beds": 2,
        "areas": ["hackney"], "must_have": ["lift"], "nice_to_have": [],
        "avoid": ["basement"], "commute_to": "Soho",
        # contact_* are not schema columns; must land only inside `data`
        "contact_name": "Alex", "contact_email": "a@x.com", "contact_phone": "07000",
    }
    s.upsert_brief(brief)

    t = fake.tables["briefs"]
    _assert_columns(t)
    row = t.upserts[0]
    assert "contact_email" not in row
    assert row["data"]["contact_email"] == "a@x.com"
    # briefs() rehydrates the full payload from `data`
    assert s.briefs()[0]["contact_email"] == "a@x.com"


def test_record_payment_filters_unknown_columns(store):
    s, fake = store
    # a payment shaped like create_order()'s output, with extra non-schema keys
    payment = {
        "id": "SIM-abc", "amount": 9.99, "status": "paid",
        "currency": "GBP", "approve_url": "http://pp", "simulated": True,
    }
    s.record_payment(payment)

    t = fake.tables["payments"]
    _assert_columns(t)
    row = t.upserts[0]
    assert set(row) <= {"id", "amount", "status", "raw"}
    # full payload stashed in raw when no explicit raw provided
    assert row["raw"]["approve_url"] == "http://pp"
    assert s.revenue() == 9.99


def test_record_payment_keeps_explicit_raw(store):
    s, fake = store
    cap = {"id": "ORD1", "status": "COMPLETED", "purchase_units": [{}]}
    s.record_payment({"id": "ORD1", "amount": 9.99, "status": "paid", "raw": cap})
    row = fake.tables["payments"].upserts[0]
    assert row["raw"] == cap


def test_match_nested_listing_round_trip(store):
    s, fake = store
    listing = {"id": "L9", "source": "otm", "url": "http://y", "price": 1800,
               "beds": 1, "address": "Bow", "pois": {"cafe": 2}}
    match = {"brief_id": "B1", "listing": listing, "score": 0.87,
             "reasons": ["under budget"], "enquiry_draft": "Hi", "status": "new"}
    s.add_match(match)

    t = fake.tables["matches"]
    _assert_columns(t)
    row = t.upserts[0]
    assert row["id"] == "B1::L9"
    assert row["listing_id"] == "L9"
    # the nested listing survives so consumers don't need a join
    out = s.matches(min_score=0.5)
    assert len(out) == 1
    assert out[0]["listing"] == listing
    assert out[0]["listing"]["pois"] == {"cafe": 2}
    # below-threshold matches are filtered out
    assert s.matches(min_score=0.9) == []


def test_matches_sorted_by_score_desc(store):
    s, _ = store
    for i, sc in enumerate([0.2, 0.9, 0.5]):
        s.add_match({"brief_id": "B", "listing": {"id": f"L{i}"}, "score": sc,
                     "reasons": [], "enquiry_draft": "", "status": "new"})
    scores = [m["score"] for m in s.matches()]
    assert scores == [0.9, 0.5, 0.2]


def test_agents_coordination(store):
    s, fake = store
    s.set_agent_status("collector", "running", brief="B1")
    s.set_agent_status("scorer", "idle")
    _assert_columns(fake.tables["agents"])

    agents = s.agents()
    assert set(agents) == {"collector", "scorer"}
    assert agents["collector"]["status"] == "running"
    assert agents["collector"]["extra"] == {"brief": "B1"}


def test_notes_coordination(store):
    s, fake = store
    s.put_note("last_scan", {"count": 12})
    s.put_note("cursor", "page-3")
    _assert_columns(fake.tables["notes"])

    assert s.get_note("last_scan") == {"count": 12}
    assert s.get_note("missing") is None
    assert s.notes() == {"last_scan": {"count": 12}, "cursor": "page-3"}


def test_enrichment_cache_round_trip(store):
    s, fake = store
    s.cache_enrichment("epc:E9 5JX", {"rating": "B", "sqm": 55}, kind="epc")
    s.cache_enrichment("commute:L9", {"walk_min": 4}, kind="commute")
    _assert_columns(fake.tables["enrichment_cache"])

    assert s.get_enrichment("epc:E9 5JX") == {"rating": "B", "sqm": 55}
    assert s.get_enrichment("commute:L9") == {"walk_min": 4}
    assert s.get_enrichment("nope") is None


def test_stats_counts(store):
    s, _ = store
    s.upsert_listing({"id": "L1", "source": "t", "url": ""})
    s.upsert_brief({"id": "B1", "text": "hi"})
    s.add_match({"brief_id": "B1", "listing": {"id": "L1"}, "score": 0.5,
                 "reasons": [], "enquiry_draft": "", "status": "new"})
    s.record_payment({"id": "P1", "amount": 9.99, "status": "paid"})
    st = s.stats()
    assert st["listings"] == 1
    assert st["matches"] == 1
    assert st["briefs"] == 1
    assert st["revenue"] == 9.99
