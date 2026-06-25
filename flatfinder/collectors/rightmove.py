"""Rightmove collector.

Rightmove embeds a JSON `"properties":[...]` array in the search results page.
NOTE: scraping Rightmove violates their ToS — for production swap this for
email-alert parsing or a licensed feed. Kept here for the hackathon demo only.
"""
import json

from ..config import RIGHTMOVE_REGION
from ..http import get
from ..models import Listing
from .base import extract_balanced, guess_postcode

BASE = "https://www.rightmove.co.uk"


def fetch(max_price: int = 2500, min_beds: int = 1, region: str | None = None) -> list[Listing]:
    region = region or RIGHTMOVE_REGION
    url = (f"{BASE}/property-to-rent/find.html?searchType=RENT"
           f"&locationIdentifier=REGION%5E{region}"
           f"&maxPrice={max_price}&minBedrooms={min_beds}")
    html = get(url)
    arr = extract_balanced(html, '"properties":')
    out: list[Listing] = []
    if not arr:
        return out
    for p in json.loads(arr):
        addr = p.get("displayAddress", "") or ""
        price = (p.get("price") or {}).get("amount")
        loc = p.get("location") or {}
        out.append(Listing(
            id=f"rm-{p.get('id')}",
            source="Rightmove",
            url=BASE + (p.get("propertyUrl") or ""),
            price=int(price) if price else None,
            beds=p.get("bedrooms"),
            baths=p.get("bathrooms"),
            address=addr,
            postcode=guess_postcode(addr),
            summary=p.get("summary", "") or "",
            property_type=p.get("propertyTypeFullDescription", "") or "",
            floorplan_url=_first_floorplan(p),
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            raw=p,
        ))
    return out


def _first_floorplan(p: dict) -> str:
    for img in (p.get("propertyImages") or {}).get("images", []) or []:
        if "floorplan" in (img.get("url", "").lower()):
            return img["url"]
    return ""
