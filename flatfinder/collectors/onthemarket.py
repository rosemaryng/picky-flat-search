"""OnTheMarket collector — parses the Next.js __NEXT_DATA__ blob.

Same ToS caveat as Rightmove: demo only.
"""
import json

from ..http import get
from ..models import Listing
from .base import extract_balanced, guess_postcode

BASE = "https://www.onthemarket.com"


def fetch(max_price: int = 2500, min_beds: int = 1, location: str = "london") -> list[Listing]:
    url = f"{BASE}/to-rent/property/{location}/?max-price={max_price}&min-bedrooms={min_beds}"
    try:
        html = get(url)
    except Exception:
        return []
    blob = extract_balanced(html, '__NEXT_DATA__" type="application/json">')
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except Exception:
        return []
    props: list[dict] = []
    _walk(data, props)
    out: list[Listing] = []
    seen = set()
    for p in props:
        pid = str(p.get("id") or p.get("property-id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        addr = p.get("display-address") or p.get("displayAddress") or ""
        price = _to_int(p.get("price"))
        link = p.get("property-link") or p.get("url") or ""
        out.append(Listing(
            id=f"otm-{pid}",
            source="OnTheMarket",
            url=(BASE + link) if link.startswith("/") else (link or url),
            price=price,
            beds=_to_int(p.get("bedrooms") or p.get("bedrooms-max")),
            address=addr,
            postcode=guess_postcode(addr),
            summary=(p.get("summary") or p.get("description") or "")[:300],
            raw=p,
        ))
    return out


def _walk(o, acc: list):
    if isinstance(o, dict):
        keys = set(o.keys())
        if "price" in keys and ({"display-address", "displayAddress"} & keys):
            acc.append(o)
        for v in o.values():
            _walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            _walk(v, acc)


def _to_int(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = "".join(ch for ch in str(v) if ch.isdigit())
    return int(digits) if digits else None
