"""Collectors pull raw listings from portals into `Listing` objects."""
from ..models import Listing
from . import onthemarket, rightmove

SOURCES = {
    "rightmove": rightmove.fetch,
    "onthemarket": onthemarket.fetch,
}


def collect_all(max_price: int = 2500, min_beds: int = 1) -> list[Listing]:
    out: list[Listing] = []
    for name, fn in SOURCES.items():
        try:
            rows = fn(max_price=max_price, min_beds=min_beds)
            out += rows
        except Exception as e:  # never let one portal break the run
            print(f"[collector:{name}] error: {e!r}")
    return out
