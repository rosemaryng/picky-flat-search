"""Persistence layer. Uses Supabase when configured, else a local JSON file so
the demo runs with zero setup. Same interface either way."""
import json
import os
import threading

from .config import LOCAL_DB_PATH, SUPABASE_KEY, SUPABASE_URL, has_supabase

_lock = threading.Lock()


class LocalStore:
    """JSON-file store: tables -> {id: row}."""

    def __init__(self, path: str = LOCAL_DB_PATH):
        self.path = os.path.abspath(path)
        self._data = {"listings": {}, "matches": {}, "briefs": {}, "viewings": {}, "payments": {}}
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

    def stats(self) -> dict:
        return {
            "listings": len(self._data["listings"]),
            "matches": len(self._data["matches"]),
            "briefs": len(self._data["briefs"]),
            "viewings": len(self._data["viewings"]),
            "revenue": self.revenue(),
        }


class SupabaseStore:
    def __init__(self):
        from supabase import create_client
        self.sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    def seen(self, listing_id: str) -> bool:
        r = self.sb.table("listings").select("id").eq("id", listing_id).execute()
        return bool(r.data)

    def upsert_listing(self, listing: dict):
        self.sb.table("listings").upsert(_flat_listing(listing)).execute()

    def add_match(self, match: dict):
        self.sb.table("matches").upsert({
            "brief_id": match["brief_id"], "listing_id": match["listing"]["id"],
            "score": match["score"], "reasons": match["reasons"],
            "enquiry_draft": match["enquiry_draft"], "status": match["status"],
        }).execute()

    def matches(self, min_score: float = 0) -> list[dict]:
        r = (self.sb.table("matches").select("*").gte("score", min_score)
             .order("score", desc=True).execute())
        return r.data or []

    def upsert_brief(self, brief: dict):
        self.sb.table("briefs").upsert(brief).execute()

    def briefs(self) -> list[dict]:
        return self.sb.table("briefs").select("*").execute().data or []

    def record_payment(self, payment: dict):
        self.sb.table("payments").upsert(payment).execute()

    def revenue(self) -> float:
        rows = self.sb.table("payments").select("amount,status").eq("status", "paid").execute().data or []
        return round(sum(float(r["amount"]) for r in rows), 2)

    def stats(self) -> dict:
        def count(t):
            return self.sb.table(t).select("id", count="exact").execute().count or 0
        return {"listings": count("listings"), "matches": count("matches"),
                "briefs": count("briefs"), "viewings": count("viewings"),
                "revenue": self.revenue()}


def _flat_listing(listing: dict) -> dict:
    keep = ("id", "source", "url", "price", "beds", "baths", "address", "postcode",
            "summary", "epc", "sqm")
    row = {k: listing.get(k) for k in keep}
    row["data"] = listing
    return row


def get_store():
    if has_supabase():
        try:
            return SupabaseStore()
        except Exception as e:
            print(f"[store] Supabase unavailable ({e!r}); using local store")
    return LocalStore()
