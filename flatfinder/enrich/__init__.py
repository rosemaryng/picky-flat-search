"""Enrichment hydrates a raw `Listing` with EPC, floorplan, and location data."""
from ..models import Listing
from . import epc, floorplan, geo


def enrich(listing: Listing) -> Listing:
    for step in (epc.enrich, floorplan.enrich, geo.enrich):
        try:
            step(listing)
        except Exception as e:
            print(f"[enrich:{step.__module__}] {e!r}")
    return listing
