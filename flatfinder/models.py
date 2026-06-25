"""Typed data structures shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class Listing:
    id: str
    source: str
    url: str
    price: Optional[int] = None          # pcm in GBP
    beds: Optional[int] = None
    baths: Optional[int] = None
    address: str = ""
    postcode: str = ""
    summary: str = ""
    property_type: str = ""
    floorplan_url: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    # enrichment (filled in later)
    epc: Optional[str] = None
    sqm: Optional[float] = None
    has_lift: Optional[bool] = None
    floor_level: Optional[str] = None
    aspect: Optional[str] = None         # e.g. "south-facing (estimated)"
    pois: dict = field(default_factory=dict)      # {"gym": 3, "supermarket": 2, ...}
    transport: dict = field(default_factory=dict)  # {"nearest_station": .., "walk_min": ..}
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Brief:
    id: str
    text: str                            # free-text wishlist
    max_price: Optional[int] = None
    min_beds: int = 0
    min_sqm: Optional[float] = None      # minimum floor area in sqm
    areas: list[str] = field(default_factory=list)
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    commute_to: str = ""                 # place to measure commute against
    contact_name: str = "Alex Tenant"
    contact_email: str = "alex@example.com"
    contact_phone: str = "07000 000000"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Match:
    brief_id: str
    listing: Listing
    score: float
    reasons: list[str] = field(default_factory=list)
    enquiry_draft: str = ""
    status: str = "new"                  # new | drafted | sent | viewing_booked

    def to_dict(self) -> dict[str, Any]:
        d = {"brief_id": self.brief_id, "score": self.score, "reasons": self.reasons,
             "enquiry_draft": self.enquiry_draft, "status": self.status}
        d["listing"] = self.listing.to_dict()
        return d
