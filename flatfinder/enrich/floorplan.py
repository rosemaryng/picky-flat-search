"""Floorplan understanding via a vision LLM.

With OPENAI_API_KEY set, sends the floorplan image to a vision model and extracts
sqm, room count, lift hints, and aspect/orientation. Without a key it falls back
to parsing the listing text, so the pipeline still runs.
"""
import json
import re

from ..config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from ..models import Listing

_SQM_RE = re.compile(r"(\d{2,4}(?:\.\d+)?)\s*(?:sq\.?\s*m|sqm|m2|m²)", re.I)
_SQFT_RE = re.compile(r"(\d{3,5})\s*(?:sq\.?\s*ft|sqft|ft2)", re.I)
_LIFT_RE = re.compile(r"\blift\b|\belevator\b", re.I)
_NOLIFT_RE = re.compile(r"no lift|without (?:a )?lift|walk[- ]?up", re.I)
_FLOOR_RE = re.compile(r"(ground|basement|lower ground|first|second|third|top)\s+floor", re.I)
_ASPECT_RE = re.compile(r"(south|north|east|west)[- ]?(?:east|west)?[- ]?facing", re.I)


def _from_text(listing: Listing) -> None:
    text = f"{listing.summary} {listing.property_type} {listing.address}"
    if listing.sqm is None:
        m = _SQM_RE.search(text)
        if m:
            listing.sqm = float(m.group(1))
        else:
            m = _SQFT_RE.search(text)
            if m:
                listing.sqm = round(float(m.group(1)) * 0.092903, 1)
    if listing.has_lift is None:
        if _NOLIFT_RE.search(text):
            listing.has_lift = False
        elif _LIFT_RE.search(text):
            listing.has_lift = True
    if listing.floor_level is None:
        m = _FLOOR_RE.search(text)
        if m:
            listing.floor_level = m.group(1).lower()
    if listing.aspect is None:
        m = _ASPECT_RE.search(text)
        if m:
            listing.aspect = m.group(0).lower()


def _from_vision(listing: Listing) -> bool:
    """Returns True if vision succeeded."""
    if not (has_openai() and listing.floorplan_url):
        return False
    try:
        from openai import OpenAI
    except Exception:
        return False
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "You are reading a property floorplan image. Return strict JSON with keys: "
        "sqm (number or null, total internal floor area in square metres), "
        "rooms (int), bedrooms (int or null), has_separate_kitchen (bool), "
        "aspect (string like 'south-facing' inferred from any compass/North arrow, else null), "
        "notes (short string). Only JSON, no prose."
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": listing.floorplan_url}},
                ],
            }],
            max_tokens=300,
        )
        txt = resp.choices[0].message.content
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        data = json.loads(txt)
        if data.get("sqm"):
            listing.sqm = float(data["sqm"])
        if data.get("aspect"):
            listing.aspect = str(data["aspect"]) + " (from floorplan)"
        listing.raw.setdefault("floorplan_ai", data)
        return True
    except Exception as e:
        print(f"[floorplan vision] {e!r}")
        return False


def enrich(listing: Listing) -> None:
    if not _from_vision(listing):
        _from_text(listing)
    else:
        _from_text(listing)  # still backfill lift/floor from text
