"""Persistence + shared memory.

Two interchangeable backends behind one interface:
- `ModalStore`  — a **named `modal.Dict`** that every agent can attach to by name,
  so multiple agents (Modal workers, other Devin sessions in the same Modal
  workspace) read/write the *same* live state. This is the shared memory.
- `LocalStore`  — a JSON file, for zero-setup offline development.

Pick the backend with FLATFINDER_STORE=modal (the Modal workers set this
automatically). Keys are namespaced so the store doubles as a coordination
blackboard between agents:

    brief:<id>      listing:<id>      match:<brief>::<listing>
    payment:<id>    agent:<name>      note:<key>
"""
import json
import os
import threading
import time

from .config import LOCAL_DB_PATH, SUPABASE_KEY, SUPABASE_URL, has_supabase

_lock = threading.Lock()

MODAL_DICT_NAME = os.environ.get("MODAL_DICT_NAME", "flatfinder-shared")


class LocalStore:
    """JSON-file store: tables -> {id: row}. Mirrors the ModalStore interface."""

    def __init__(self, path: str = LOCAL_DB_PATH):
        self.path = os.path.abspath(path)
        self._data = {"listings": {}, "matches": {}, "briefs": {},
                      "viewings": {}, "payments": {}, "agents": {}, "notes": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._data.update(json.load(f))
            except Exception:
                pass

    def _flush(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=1, default=str)

    # --- data ---
    def seen(self, listing_id: str) -> bool:
        return listing_id in self._data["listings"]

    def upsert_listing(self, listing: dict):
        with _lock:
            self._data["listings"][listing["id"]] = listing
            self._flush()

    def add_match(self, match: dict):
        with _lock:
            key = f"{match['brief_id']}::{match['listing']['id']}"
            self._data["matches"][key] = match
            self._flush()

    def matches(self, min_score: float = 0) -> list[dict]:
        rows = [m for m in self._data["matches"].values() if m["score"] >= min_score]
        return sorted(rows, key=lambda m: -m["score"])

    def upsert_brief(self, brief: dict):
        with _lock:
            self._data["briefs"][brief["id"]] = brief
            self._flush()

    def briefs(self) -> list[dict]:
        return list(self._data["briefs"].values())

    def record_payment(self, payment: dict):
        with _lock:
            self._data["payments"][payment["id"]] = payment
            self._flush()

    def revenue(self) -> float:
        return round(sum(float(p.get("amount", 0)) for p in self._data["payments"].values()
                         if p.get("status") == "paid"), 2)

    # --- shared coordination (agents can see each other) ---
    def set_agent_status(self, name: str, status: str, **extra):
        with _lock:
            self._data["agents"][name] = {"status": status, "ts": time.time(), **extra}
            self._flush()

    def agents(self) -> dict:
        return dict(self._data["agents"])

    def put_note(self, key: str, value):
        with _lock:
            self._data["notes"][key] = {"value": value, "ts": time.time()}
            self._flush()

    def get_note(self, key: str):
        rec = self._data["notes"].get(key)
        return rec["value"] if rec else None

    def notes(self) -> dict:
        return {k: v["value"] for k, v in self._data["notes"].items()}

    def stats(self) -> dict:
        return {
            "listings": len(self._data["listings"]),
            "matches": len(self._data["matches"]),
            "briefs": len(self._data["briefs"]),
            "viewings": len(self._data["viewings"]),
            "agents": len(self._data["agents"]),
            "revenue": self.revenue(),
        }


class ModalStore:
    """Shared memory backed by a named `modal.Dict`.

    Every agent that does `modal.Dict.from_name(MODAL_DICT_NAME)` sees the same
    state, so this is the cross-agent shared memory + coordination blackboard.
    """

    def __init__(self, name: str = MODAL_DICT_NAME):
        import modal  # lazy: only needed when this backend is selected
        self.d = modal.Dict.from_name(name, create_if_missing=True)

    # key helpers
    @staticmethod
    def _k(ns: str, key: str) -> str:
        return f"{ns}:{key}"

    def _scan(self, ns: str) -> list:
        prefix = ns + ":"
        out = []
        for k, v in self.d.items():
            if isinstance(k, str) and k.startswith(prefix):
                out.append(v)
        return out

    # --- data ---
    def seen(self, listing_id: str) -> bool:
        return self._k("listing", listing_id) in self.d

    def upsert_listing(self, listing: dict):
        self.d[self._k("listing", listing["id"])] = listing

    def add_match(self, match: dict):
        key = f"{match['brief_id']}::{match['listing']['id']}"
        self.d[self._k("match", key)] = match

    def matches(self, min_score: float = 0) -> list[dict]:
        rows = [m for m in self._scan("match") if m.get("score", 0) >= min_score]
        return sorted(rows, key=lambda m: -m["score"])

    def upsert_brief(self, brief: dict):
        self.d[self._k("brief", brief["id"])] = brief

    def briefs(self) -> list[dict]:
        return self._scan("brief")

    def record_payment(self, payment: dict):
        self.d[self._k("payment", payment["id"])] = payment

    def revenue(self) -> float:
        return round(sum(float(p.get("amount", 0)) for p in self._scan("payment")
                         if p.get("status") == "paid"), 2)

    # --- shared coordination ---
    def set_agent_status(self, name: str, status: str, **extra):
        self.d[self._k("agent", name)] = {"status": status, "ts": time.time(), **extra}

    def agents(self) -> dict:
        out = {}
        for k, v in self.d.items():
            if isinstance(k, str) and k.startswith("agent:"):
                out[k[len("agent:"):]] = v
        return out

    def put_note(self, key: str, value):
        self.d[self._k("note", key)] = {"value": value, "ts": time.time()}

    def get_note(self, key: str):
        rec = self.d.get(self._k("note", key))
        return rec["value"] if rec else None

    def notes(self) -> dict:
        out = {}
        for k, v in self.d.items():
            if isinstance(k, str) and k.startswith("note:"):
                out[k[len("note:"):]] = v.get("value")
        return out

    def stats(self) -> dict:
        return {
            "listings": len(self._scan("listing")),
            "matches": len(self._scan("match")),
            "briefs": len(self._scan("brief")),
            "agents": len(self.agents()),
            "viewings": 0,
            "revenue": self.revenue(),
        }


class SupabaseStore:
    """Postgres-backed shared store. Like ModalStore, every agent connects to the
    same project, so it's shared memory across agents. Match rows keep the full
    nested `listing` (jsonb) so the interface matches LocalStore/ModalStore."""

    def __init__(self):
        from supabase import create_client
        self.sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # --- data ---
    def seen(self, listing_id: str) -> bool:
        r = self.sb.table("listings").select("id").eq("id", listing_id).execute()
        return bool(r.data)

    def upsert_listing(self, listing: dict):
        self.sb.table("listings").upsert(_flat_listing(listing)).execute()

    def add_match(self, match: dict):
        self.sb.table("matches").upsert({
            "id": f"{match['brief_id']}::{match['listing']['id']}",
            "brief_id": match["brief_id"], "listing_id": match["listing"]["id"],
            "score": match["score"], "reasons": match["reasons"],
            "enquiry_draft": match["enquiry_draft"], "status": match["status"],
            "listing": match["listing"],  # keep nested listing so consumers work
        }).execute()

    def matches(self, min_score: float = 0) -> list[dict]:
        r = (self.sb.table("matches").select("*").gte("score", min_score)
             .order("score", desc=True).execute())
        return r.data or []

    def upsert_brief(self, brief: dict):
        self.sb.table("briefs").upsert(_flat_brief(brief)).execute()

    def briefs(self) -> list[dict]:
        rows = self.sb.table("briefs").select("*").execute().data or []
        # full brief (incl. contact_*) is kept in the jsonb `data` column
        return [r.get("data") or r for r in rows]

    def record_payment(self, payment: dict):
        self.sb.table("payments").upsert(payment).execute()

    def revenue(self) -> float:
        rows = (self.sb.table("payments").select("amount,status")
                .eq("status", "paid").execute().data or [])
        return round(sum(float(r["amount"]) for r in rows), 2)

    # --- shared coordination ---
    def set_agent_status(self, name: str, status: str, **extra):
        self.sb.table("agents").upsert({
            "name": name, "status": status, "ts": time.time(), "extra": extra,
        }).execute()

    def agents(self) -> dict:
        rows = self.sb.table("agents").select("*").execute().data or []
        return {r["name"]: r for r in rows}

    def put_note(self, key: str, value):
        self.sb.table("notes").upsert({"key": key, "value": value, "ts": time.time()}).execute()

    def get_note(self, key: str):
        r = self.sb.table("notes").select("value").eq("key", key).execute().data or []
        return r[0]["value"] if r else None

    def notes(self) -> dict:
        rows = self.sb.table("notes").select("*").execute().data or []
        return {r["key"]: r["value"] for r in rows}

    def stats(self) -> dict:
        def count(t):
            return self.sb.table(t).select("id", count="exact").execute().count or 0
        return {"listings": count("listings"), "matches": count("matches"),
                "briefs": count("briefs"), "viewings": 0,
                "agents": len(self.agents()), "revenue": self.revenue()}


def _flat_listing(listing: dict) -> dict:
    keep = ("id", "source", "url", "price", "beds", "baths", "address", "postcode",
            "summary", "epc", "sqm")
    row = {k: listing.get(k) for k in keep}
    row["data"] = listing
    return row


def _flat_brief(brief: dict) -> dict:
    """Keep only schema columns; stash the full brief (incl. contact_*) in `data`."""
    keep = ("id", "text", "max_price", "min_beds", "areas", "must_have",
            "nice_to_have", "avoid", "commute_to")
    row = {k: brief.get(k) for k in keep}
    row["data"] = brief
    return row


def get_store():
    """Auto-pick the backend, or honor FLATFINDER_STORE ("supabase"|"modal"|"local").

    Auto-detect order: Supabase (if SUPABASE_URL/KEY set) -> local JSON.
    The shared modal.Dict is used when FLATFINDER_STORE=modal (set by the Modal
    workers); it isn't auto-detected because it requires a Modal context.
    All backends expose the same interface; Supabase/modal.Dict are shared across agents.
    """
    forced = os.environ.get("FLATFINDER_STORE", "")
    if forced == "local":
        return LocalStore()
    if forced == "supabase" or (not forced and has_supabase()):
        try:
            return SupabaseStore()
        except Exception as e:
            print(f"[store] Supabase unavailable ({e!r}); falling back")
    if forced == "modal":
        try:
            return ModalStore()
        except Exception as e:
            print(f"[store] Modal shared store unavailable ({e!r}); using local store")
    return LocalStore()
