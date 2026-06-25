"""Location enrichment: coordinates, nearby POIs, and transport links.

Free data sources used:
- postcodes.io   -> postcode -> lat/lng (no key)
- Overpass (OSM) -> count POIs (gym/supermarket/restaurant) near a point (no key)
- TfL Unified API-> nearest station + (optional) journey time (free; key optional)
All calls are best-effort: failures just leave fields empty.
"""
from ..config import TFL_APP_KEY
from ..http import get_json, quote
from ..models import Listing

POSTCODES_IO = "https://api.postcodes.io/postcodes/"
OVERPASS = "https://overpass-api.de/api/interpreter"
TFL = "https://api.tfl.gov.uk"

POI_TAGS = {
    "gym": 'leisure=fitness_centre',
    "supermarket": 'shop=supermarket',
    "restaurant": 'amenity=restaurant',
    "cafe": 'amenity=cafe',
    "park": 'leisure=park',
}


def geocode(listing: Listing) -> None:
    if listing.lat and listing.lng:
        return
    if not listing.postcode:
        return
    try:
        data = get_json(POSTCODES_IO + quote(listing.postcode))
        res = data.get("result")
        if res:
            listing.lat = res.get("latitude")
            listing.lng = res.get("longitude")
    except Exception:
        pass


def nearby_pois(listing: Listing, radius_m: int = 600) -> None:
    if not (listing.lat and listing.lng):
        return
    parts = []
    for name, tag in POI_TAGS.items():
        k, v = tag.split("=")
        parts.append(f'node(around:{radius_m},{listing.lat},{listing.lng})[{k}={v}];')
    query = f"[out:json][timeout:15];({''.join(parts)});out tags;"
    try:
        import urllib.parse
        import urllib.request
        body = urllib.parse.urlencode({"data": query}).encode()
        req = urllib.request.Request(OVERPASS, data=body,
                                     headers={"User-Agent": "flat-finder/0.1"})
        import json as _json
        with urllib.request.urlopen(req, timeout=25) as r:
            data = _json.loads(r.read().decode())
    except Exception:
        return
    counts = {k: 0 for k in POI_TAGS}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        for name, tag in POI_TAGS.items():
            k, v = tag.split("=")
            if tags.get(k) == v:
                counts[name] += 1
    listing.pois = counts


def transport(listing: Listing) -> None:
    if not (listing.lat and listing.lng):
        return
    key = f"?app_key={TFL_APP_KEY}" if TFL_APP_KEY else ""
    try:
        url = (f"{TFL}/StopPoint{key}{'&' if key else '?'}"
               f"lat={listing.lat}&lon={listing.lng}&stopTypes="
               "NaptanMetroStation,NaptanRailStation&radius=1500")
        data = get_json(url)
        sps = data.get("stopPoints") or []
        if sps:
            nearest = min(sps, key=lambda s: s.get("distance", 1e9))
            listing.transport = {
                "nearest_station": nearest.get("commonName"),
                "distance_m": round(nearest.get("distance", 0)),
                "walk_min": round(nearest.get("distance", 0) / 80),  # ~80 m/min
            }
    except Exception:
        pass


def enrich(listing: Listing) -> None:
    geocode(listing)
    nearby_pois(listing)
    transport(listing)
