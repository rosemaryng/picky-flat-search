"""Score a listing against a brief.

Uses an LLM for nuanced matching when OPENAI_API_KEY is set; otherwise a
transparent deterministic scorer so the demo runs offline. Both return a
0-100 score plus human-readable reasons.

The deterministic scorer is tri-state aware: every feature resolves to present
(reward), absent (penalty) or unknown (mild penalty + a flag for the human),
so a missing data point never silently passes as a match.
"""
import json
import re

from .config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from .models import Brief, Listing

# EPC ratings ordered best -> worst. Lower index == better.
_EPC_ORDER = ["A", "B", "C", "D", "E", "F", "G"]
_EPC_REQ_RE = re.compile(r"epc\s*([a-g])", re.I)

# scoring weights, kept in one place so trade-offs are easy to read/tune
_W_MUST_PRESENT = 8.0
_W_MUST_ABSENT = -18.0      # missing a hard requirement is a big deal
_W_MUST_UNKNOWN = -3.0      # can't confirm -> mild penalty, flag for human
_W_NICE_PRESENT = 4.0
_W_AVOID_PRESENT = -16.0    # a dealbreaker that's present is nearly as bad as missing a must
_W_AVOID_UNKNOWN = -2.0


def score(listing: Listing, brief: Brief) -> tuple[float, list[str]]:
    if has_openai():
        out = _llm_score(listing, brief)
        if out is not None:
            return out
    return _rule_score(listing, brief)


def _epc_meets(have: str | None, want_letter: str) -> bool | None:
    """Tri-state: does an EPC rating meet a 'want or better' floor?"""
    if not have:
        return None
    have = have.strip().upper()[:1]
    want = want_letter.strip().upper()[:1]
    if have not in _EPC_ORDER or want not in _EPC_ORDER:
        return None
    return _EPC_ORDER.index(have) <= _EPC_ORDER.index(want)


def _rule_score(listing: Listing, brief: Brief) -> tuple[float, list[str]]:
    s = 50.0
    reasons: list[str] = []
    hay = " ".join(str(x).lower() for x in (
        listing.address, listing.summary, listing.property_type)).lower()

    # budget — reward headroom under the cap, penalise going over proportionally
    if brief.max_price and listing.price:
        if listing.price <= brief.max_price:
            headroom = (brief.max_price - listing.price) / brief.max_price
            s += 12 * headroom
            reasons.append(f"under budget (£{listing.price} ≤ £{brief.max_price})")
        else:
            over = (listing.price - brief.max_price) / brief.max_price
            s -= 30 + 20 * min(over, 1.0)  # the further over, the worse (capped)
            reasons.append(f"OVER budget (£{listing.price} > £{brief.max_price})")

    # beds — reward meeting the minimum, penalise falling short
    if listing.beds is not None and brief.min_beds:
        if listing.beds >= brief.min_beds:
            s += 5
            reasons.append(f"{listing.beds} beds (≥{brief.min_beds})")
        else:
            s -= 15
            reasons.append(f"only {listing.beds} beds (<{brief.min_beds})")

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
            s += _W_MUST_PRESENT
            reasons.append(f"must: {kw}")
        elif state is False:
            s += _W_MUST_ABSENT
            reasons.append(f"MISSING must: {kw}")
        else:  # unknown — mild penalty, flag for the human
            s += _W_MUST_UNKNOWN
            reasons.append(f"must (unconfirmed): {kw}")
    for kw in brief.nice_to_have:
        if _feature_state(kw, listing, hay) is True:
            s += _W_NICE_PRESENT
            reasons.append(f"+{kw}")
    for kw in brief.avoid:
        state = _feature_state(kw, listing, hay)
        if state is True:
            s += _W_AVOID_PRESENT
            reasons.append(f"AVOID present: {kw}")
        elif state is None:
            s += _W_AVOID_UNKNOWN
            reasons.append(f"avoid (unconfirmed): {kw}")

    # commute — reward a known, short walk to transport when the brief asks for one
    walk = listing.transport.get("walk_min")
    if walk is not None and walk <= 10:
        s += 6
        reasons.append(f"{walk}min walk to {listing.transport.get('nearest_station', 'station')}")
    if brief.commute_to:
        dest = listing.transport.get("commute_min")
        if dest is not None:
            if dest <= 35:
                s += 8
                reasons.append(f"{dest}min commute to {brief.commute_to}")
            else:
                s -= 4
                reasons.append(f"{dest}min commute to {brief.commute_to} (far)")

    # enrichment-aware bonuses
    if listing.epc and listing.epc.upper()[:1] in ("A", "B", "C"):
        s += 4
        reasons.append(f"EPC {listing.epc}")
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

    # EPC floor requirement, e.g. "epc c or better"
    m = _EPC_REQ_RE.search(kw)
    if m:
        return _epc_meets(listing.epc, m.group(1))

    if kw == "lift":
        return listing.has_lift  # True / False / None
    if kw in ("no lift", "walk-up", "walk up"):
        return (listing.has_lift is False) if listing.has_lift is not None else None

    if "facing" in kw or kw == "dual aspect":
        if listing.aspect:
            want = "dual" if kw == "dual aspect" else kw.split()[0]
            return want in listing.aspect.lower()
        return None

    if kw in ("ground floor", "basement"):
        if listing.floor_level:
            return kw.split()[0] in listing.floor_level.lower()
        return True if kw in hay else None

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
        "Rules: heavily penalise over-budget and any missing must-have or present avoid. "
        "If a fact needed to confirm a must-have is null/unknown, apply only a mild penalty "
        "and say it is unconfirmed (never assume it passes). Reward area, short commute to "
        "commute_to, good EPC, generous sqm, and nice-to-haves. Reasons must be short and "
        "specific (cite the number/fact). Return STRICT JSON only: "
        '{"score": <0-100>, "reasons": ["short reason", ...]}'
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=300,
        )
        txt = resp.choices[0].message.content
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        data = json.loads(txt)
        return float(data["score"]), list(data.get("reasons", []))
    except Exception as e:
        print(f"[llm_score] {e!r}")
        return None
