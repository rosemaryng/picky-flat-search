"""Floorplan understanding via a vision LLM.

With OPENAI_API_KEY set, sends the floorplan image to a vision model and extracts
the total internal area (sqm) and the aspect/orientation, plus room count and
lift hints. Without a key it falls back to parsing the listing text (incl. sqft
conversion and room dimensions like "4.1m x 3.2m"), so the pipeline still runs.
"""
import json
import re

from ..config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from ..models import Listing

_SQM_RE = re.compile(
    r"(\d{2,4}(?:\.\d+)?)\s*(?:sq\.?\s*m(?:etres?|eters?)?|sqm|m2|m²|square\s+m(?:etres?|eters?))",
    re.I,
)
_SQFT_RE = re.compile(r"(\d{3,5})\s*(?:sq\.?\s*ft|sqft|ft2|ft²|square\s+f(?:ee|oo)t)", re.I)
# room dimensions, e.g. "4.10m x 3.25m" / "13'1 x 10'8" -> used to estimate area
_DIM_M_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*m\s*[x×]\s*(\d{1,2}(?:\.\d+)?)\s*m", re.I)
_LIFT_RE = re.compile(r"\blift\b|\belevator\b", re.I)
_NOLIFT_RE = re.compile(r"no lift|without (?:a )?lift|walk[- ]?up", re.I)
_FLOOR_RE = re.compile(r"(ground|basement|lower ground|first|second|third|top)\s+floor", re.I)
_ASPECT_RE = re.compile(r"(south|north|east|west)[- ]?(?:east|west)?[- ]?facing", re.I)
_DUAL_RE = re.compile(r"dual[- ]aspect", re.I)


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
            else:
                # last resort: sum room dimensions (metres) into an estimate
                dims = _DIM_M_RE.findall(text)
                if dims:
                    area = sum(float(w) * float(h) for w, h in dims)
                    if area >= 10:  # ignore noise from tiny fragments
                        listing.sqm = round(area, 1)
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
        if _DUAL_RE.search(text):
            listing.aspect = "dual aspect"
        else:
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
        "You are reading a single property floorplan image. Extract facts and return "
        "STRICT JSON only (no prose, no markdown) with exactly these keys:\n"
        '  "sqm": total internal floor area in square metres as a number, or null. '
        "Prefer a printed total area (e.g. 'Total = 58.3 sq m', or sq ft / 1000 = sq m). "
        "If only a sq ft figure is shown, convert it (sqft * 0.0929). If no total is "
        "printed, sum the individual room dimensions you can read; else null.\n"
        '  "aspect": the orientation as a token like "south-facing", "north-east-facing" '
        "or \"dual aspect\", inferred ONLY from a compass/North arrow on the plan and the "
        "side the main living-room windows face; null if there is no compass.\n"
        '  "rooms": total number of rooms as an int.\n'
        '  "bedrooms": number of bedrooms as an int, or null.\n'
        '  "has_separate_kitchen": true if the kitchen is its own room (not open-plan).\n'
        '  "has_lift": true/false/null if the plan indicates a lift, else null.\n'
        '  "notes": one short sentence of caveats (e.g. "area estimated from rooms").\n'
        "Be conservative: use null rather than guessing when the plan is unclear."
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
            temperature=0,
            max_tokens=300,
        )
        txt = resp.choices[0].message.content
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        data = json.loads(txt)
        if data.get("sqm"):
            listing.sqm = float(data["sqm"])
        if data.get("aspect"):
            listing.aspect = str(data["aspect"]) + " (from floorplan)"
        if listing.has_lift is None and isinstance(data.get("has_lift"), bool):
            listing.has_lift = data["has_lift"]
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
