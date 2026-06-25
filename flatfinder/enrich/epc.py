"""EPC enrichment.

Two paths:
1. Pull the rating off the listing text if present (free, no key).
2. (Optional) The official gov.uk EPC Open Data API gives rating + floor area by
   postcode. It needs a free API key (register at epc.opendatacommunities.org).
   Set EPC_API_KEY (an email:apikey base64) to enable.
"""
import os
import re

from ..http import get_json
from ..models import Listing

EPC_API = "https://epc.opendatacommunities.org/api/v1/domestic/search"
EPC_KEY = os.environ.get("EPC_API_KEY", "")

_RATING_RE = re.compile(r"\bEPC[^A-G]{0,12}\b([A-G])\b", re.I)


def enrich(listing: Listing) -> None:
    # 1. cheap: scrape rating from text
    if listing.epc is None:
        text = f"{listing.summary} {listing.property_type}"
        m = _RATING_RE.search(text)
        if m:
            listing.epc = m.group(1).upper()

    # 2. official API (optional)
    if (listing.epc is None or listing.sqm is None) and EPC_KEY and listing.postcode:
        try:
            data = get_json(
                f"{EPC_API}?postcode={listing.postcode.replace(' ', '%20')}&size=1",
                headers={"Authorization": f"Basic {EPC_KEY}", "Accept": "application/json"},
            )
            rows = data.get("rows") or []
            if rows:
                r = rows[0]
                listing.epc = listing.epc or r.get("current-energy-rating")
                if listing.sqm is None and r.get("total-floor-area"):
                    listing.sqm = float(r["total-floor-area"])
        except Exception:
            pass
