"""Score a listing against a brief.

Uses an LLM for nuanced matching when OPENAI_API_KEY is set; otherwise a
transparent deterministic scorer so the demo runs offline. Both return a
0-100 score plus human-readable reasons.
"""
import json

from .config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from .models import Brief, Listing


def score(listing: Listing, brief: Brief) -> tuple[float, list[str]]:
    if has_openai():
        out = _llm_score(listing, brief)
        if out is not None:
            return out
    return _rule_score(listing, brief)


def _rule_score(listing: Listing, brief: Brief) -> tuple[float, list[str]]:
    s = 50.0
    reasons: list[str] = []
    hay = " ".join(str(x).lower() for x in (
        listing.address, listing.summary, listing.property_type)).lower()

    # budget
    if brief.max_price and listing.price:
        if listing.price <= brief.max_price:
            s += 12 * (brief.max_price - listing.price) / brief.max_price
            reasons.append(f"under budget (£{listing.price})")
        else:
            s -= 30
            reasons.append(f"OVER budget (£{listing.price} > £{brief.max_price})")

    # beds
    if listing.beds is not None and listing.beds >= brief.min_beds:
        s += 5

    # area match
    for a in brief.areas:
        if a.lower() in hay:
            s += 12
            reasons.append(f"area: {a}")
            break

    # explicit must/nice/avoid + structured fields (tri-state aware)
    for kw in brief.must_have:
        state = _feature_state(kw, listing, hay)
        if state is True:
            s += 8
            reasons.append(f"must: {kw}")
        elif state is False:
            s -= 12
            reasons.append(f"MISSING must: {kw}")
        else:  # unknown — mild penalty, flag for the human
            s -= 3
            reasons.append(f"must (unconfirmed): {kw}")
    for kw in brief.nice_to_have:
        if _feature_state(kw, listing, hay) is True:
            s += 4
            reasons.append(f"+{kw}")
    for kw in brief.avoid:
        if _feature_state(kw, listing, hay) is True:
            s -= 8
            reasons.append(f"-{kw}")

    # enrichment-aware bonuses
    if listing.epc and listing.epc <= "C":
        s += 4
        reasons.append(f"EPC {listing.epc}")
    if listing.transport.get("walk_min") is not None and listing.transport["walk_min"] <= 10:
        s += 6
        reasons.append(f"{listing.transport['walk_min']}min to {listing.transport.get('nearest_station','station')}")
    if listing.pois.get("gym"):
        s += 2
        reasons.append(f"{listing.pois['gym']} gyms nearby")
    if listing.pois.get("supermarket"):
        s += 2
        reasons.append(f"{listing.pois['supermarket']} supermarkets nearby")
    if listing.sqm:
        reasons.append(f"{listing.sqm:.0f} sqm")

    return max(0, min(100, round(s, 1))), reasons


def _feature_state(kw: str, listing: Listing, hay: str):
    """Tri-state: True (present), False (absent), None (unknown)."""
    kw = kw.lower().strip()
    if kw == "lift":
        return listing.has_lift  # True / False / None
    if kw in ("no lift", "walk-up"):
        return (listing.has_lift is False) if listing.has_lift is not None else None
    if "facing" in kw:
        if listing.aspect:
            return kw.split()[0] in listing.aspect
        return None
    if kw == "gym":
        return True if listing.pois.get("gym") else (None if not listing.pois else False)
    if kw in ("supermarket", "groceries"):
        return True if listing.pois.get("supermarket") else (None if not listing.pois else False)
    return True if kw in hay else False


def _llm_score(listing: Listing, brief: Brief):
    try:
        from openai import OpenAI
    except Exception:
        return None
    client = OpenAI(api_key=OPENAI_API_KEY)
    facts = {
        "price_pcm": listing.price, "beds": listing.beds, "baths": listing.baths,
        "address": listing.address, "type": listing.property_type,
        "summary": listing.summary, "epc": listing.epc, "sqm": listing.sqm,
        "has_lift": listing.has_lift, "floor_level": listing.floor_level,
        "aspect": listing.aspect, "pois": listing.pois, "transport": listing.transport,
    }
    prompt = (
        "Score how well this rental listing matches the tenant's brief from 0-100.\n"
        f"BRIEF (free text): {brief.text}\n"
        f"BRIEF (structured): max_price={brief.max_price}, min_beds={brief.min_beds}, "
        f"areas={brief.areas}, must_have={brief.must_have}, nice_to_have={brief.nice_to_have}, "
        f"avoid={brief.avoid}, commute_to={brief.commute_to}\n"
        f"LISTING FACTS: {json.dumps(facts)}\n"
        "Penalise over-budget and missing must-haves heavily. Reward area, commute, "
        "EPC, sqm, and nice-to-haves. Return strict JSON: "
        '{"score": <0-100>, "reasons": ["short reason", ...]}'
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        txt = resp.choices[0].message.content
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        data = json.loads(txt)
        return float(data["score"]), list(data.get("reasons", []))
    except Exception as e:
        print(f"[llm_score] {e!r}")
        return None
