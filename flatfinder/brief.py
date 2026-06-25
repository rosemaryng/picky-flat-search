"""Turn a free-text wishlist into a structured Brief.

LLM-powered when a key is present; otherwise a deterministic keyword/regex
heuristic so the whole pipeline works offline with no API key. The heuristic is
intentionally strong: it understands budgets (pcm/pw, "2.5k", ranges), bed
ranges, London areas, must/nice/avoid features, EPC floors ("EPC C or better"),
orientation ("south facing") and a commute target.
"""
import json
import re

from .config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from .models import Brief

_LONDON_AREAS = [
    "shoreditch", "hackney", "islington", "clapton", "dalston", "london fields",
    "victoria park", "bethnal green", "hoxton", "stoke newington", "peckham",
    "brixton", "clapham", "camden", "kentish town", "walthamstow", "leyton",
    "bow", "stratford", "wapping", "canary wharf", "greenwich", "deptford",
    "notting hill", "marylebone", "fulham", "wandsworth",
]
_FEATURES = ["balcony", "garden", "lift", "no lift", "furnished", "unfurnished",
             "gym", "parking", "modern", "bright", "spacious", "south facing",
             "north facing", "east facing", "west facing", "dual aspect",
             "separate kitchen", "open plan", "basement", "ground floor",
             "supermarket", "groceries", "dishwasher", "pet friendly",
             "outdoor space", "concierge", "period"]

# words that, when they appear just before a feature, force it into a bucket
_AVOID_RE = re.compile(r"\b(no|avoid|without|not|don'?t|never|exclude)\b")
_MUST_RE = re.compile(r"\b(must|need|require[ds]?|essential|non[- ]?negotiable|has to)\b")
_NICE_RE = re.compile(r"\b(ideally|prefer(?:ably)?|would like|nice to have|bonus|hopefully|like)\b")
# features that are almost always things people want to *avoid*
_DEFAULT_AVOID = {"basement", "ground floor", "no lift"}


def parse(text: str, **contact) -> Brief:
    bid = contact.pop("id", "brief-1")
    if has_openai():
        b = _llm_parse(text, bid)
        if b is not None:
            for k, v in contact.items():
                setattr(b, k, v)
            return b
    return _heuristic_parse(text, bid, **contact)


# --------------------------------------------------------------------------- #
# Deterministic offline parser
# --------------------------------------------------------------------------- #
def _to_amount(num: str, k: bool) -> int | None:
    """'2,500' -> 2500, '2.5'+k -> 2500."""
    num = num.replace(",", "").strip().rstrip(".")
    if not num:
        return None
    try:
        val = float(num)
    except ValueError:
        return None
    if k:
        val *= 1000
    return int(round(val))


def _parse_budget(low: str) -> int | None:
    """Monthly budget cap in GBP. Understands pcm/pw, 'k', and ranges."""
    # weekly rent -> convert to pcm (annualise / 12)
    wk = re.search(r"£?\s*(\d[\d,.]*)\s*(k)?\s*(?:pw|per week|a week|/\s*w(?:k|eek)?|p/?w)\b", low)
    if wk:
        amt = _to_amount(wk.group(1), bool(wk.group(2)))
        if amt:
            return int(round(amt * 52 / 12))
    # explicit cap phrase wins ("under/up to/max/budget/no more than ...")
    cap = re.search(
        r"(?:under|below|max(?:imum)?|budget(?:\s+of)?|up to|no more than|less than|<=?|≤|around|about|~)"
        r"\s*£?\s*(\d[\d,.]*)\s*(k)?",
        low,
    )
    if cap:
        amt = _to_amount(cap.group(1), bool(cap.group(2)))
        if amt and amt >= 100:
            return amt
    # range "between X and Y" / "X-Y" -> the upper figure is the cap
    rng = re.search(
        r"£\s*(\d[\d,.]*)\s*(k)?\s*(?:-|–|to|and)\s*£?\s*(\d[\d,.]*)\s*(k)?",
        low,
    )
    if rng:
        hi = _to_amount(rng.group(3), bool(rng.group(4)))
        if hi and hi >= 100:
            return hi
    # bare figure that carries a currency or period marker
    gen = re.search(
        r"(?:£\s*(\d[\d,.]*)\s*(k)?)|(?:(\d[\d,.]*)\s*(k)?\s*(?:pcm|pm|per month|a month|/mo|monthly))",
        low,
    )
    if gen:
        if gen.group(1) is not None:
            amt = _to_amount(gen.group(1), bool(gen.group(2)))
        else:
            amt = _to_amount(gen.group(3), bool(gen.group(4)))
        if amt and amt >= 100:
            return amt
    return None


def _parse_beds(low: str) -> int:
    """Minimum bedroom count. Ranges/at-least take the lower bound."""
    m = re.search(r"(\d)\s*(?:-|–|to|or)\s*\d\s*(?:bed|bedroom)", low)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:at least|min(?:imum)?|>=?)\s*(\d)\s*(?:bed|bedroom)", low)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)\s*\+\s*(?:bed|bedroom)", low)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)\s*(?:bed|bedroom)", low)
    if m:
        return int(m.group(1))
    if re.search(r"\bstudio\b", low):
        return 0
    return 0


def _parse_epc(low: str) -> str | None:
    """Normalise an EPC floor to the token 'epc <letter> or better'."""
    # range like "EPC A-C" / "EPC A to C" -> the worst acceptable letter is the cap
    m = re.search(r"epc\s*[a-g]\s*(?:-|–|to)\s*([a-g])\b", low)
    if m:
        return f"epc {m.group(1).lower()} or better"
    m = re.search(
        r"epc\s*(?:rating)?\s*(?:of|=|:|at\s+least|min(?:imum)?)?\s*"
        r"([a-g])\b(?:\s*(?:or|\+|and)?\s*(?:better|above|higher|up))?",
        low,
    )
    if m:
        return f"epc {m.group(1).lower()} or better"
    return None


def _parse_commute(low: str) -> str:
    """Best-effort commute target (a place name)."""
    patterns = [
        r"commute\s+(?:of\s+[\w ]+?\s+)?(?:to|into)\s+([a-z][a-z '&]{2,30}?)",
        r"(?:work|office|job)\s+(?:in|at|near|by)\s+([a-z][a-z '&]{2,30}?)",
        r"(?:close to|near|next to|walking distance to|within [\w ]*? of)\s+"
        r"([a-z][a-z '&]{2,30}?)",
    ]
    for pat in patterns:
        m = re.search(pat + r"(?:[,.]| station| tube| underground|$| in | for | so )", low)
        if m:
            place = m.group(1).strip(" '&")
            # drop generic filler so we keep a real destination
            if place and place not in {"the", "a", "my", "work", "an"}:
                return place
    return ""


def _classify_feature(before: str, feature: str, must, nice, avoid) -> None:
    if _AVOID_RE.search(before) or feature in _DEFAULT_AVOID:
        bucket = avoid
    elif _MUST_RE.search(before):
        bucket = must
    elif _NICE_RE.search(before):
        bucket = nice
    else:
        bucket = nice
    if feature not in bucket:
        bucket.append(feature)


def _heuristic_parse(text: str, bid: str, **contact) -> Brief:
    low = text.lower()
    max_price = _parse_budget(low)
    beds = _parse_beds(low)
    areas = [a for a in _LONDON_AREAS if a in low]

    must, nice, avoid = [], [], []
    consumed: list[tuple[int, int]] = []  # spans already claimed by a longer feature

    def _overlaps(s: int, e: int) -> bool:
        return any(s < ce and e > cs for cs, ce in consumed)

    # longest features first so "no lift" claims the span before bare "lift" can
    for f in sorted(_FEATURES, key=len, reverse=True):
        for mt in re.finditer(re.escape(f), low):
            s, e = mt.start(), mt.end()
            if _overlaps(s, e):
                continue
            consumed.append((s, e))
            before = low[max(0, s - 24):s]  # classify by words just before the feature
            _classify_feature(before, f, must, nice, avoid)

    epc = _parse_epc(low)
    if epc:
        # an EPC floor is normally a hard requirement
        target = nice if _NICE_RE.search(low) and not _MUST_RE.search(low) else must
        if epc not in target:
            target.append(epc)

    commute = _parse_commute(low)

    b = Brief(id=bid, text=text, max_price=max_price, min_beds=beds, areas=areas,
              must_have=must, nice_to_have=nice, avoid=avoid, commute_to=commute)
    for k, v in contact.items():
        setattr(b, k, v)
    return b


# --------------------------------------------------------------------------- #
# LLM parser
# --------------------------------------------------------------------------- #
def _llm_parse(text: str, bid: str):
    try:
        from openai import OpenAI
    except Exception:
        return None
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "You extract a structured London rental brief from a tenant's free text.\n"
        "Return STRICT JSON only (no prose, no markdown) with exactly these keys:\n"
        '  "max_price": monthly budget cap in GBP as an int, or null. Convert per-week '
        "rents to pcm (weekly*52/12) and \"2.5k\" to 2500. For a range use the upper bound.\n"
        '  "min_beds": minimum bedrooms as an int (studio=0; for "1-2 bed" use the lower 1).\n'
        '  "areas": list of London neighbourhood/area names mentioned (lowercase).\n'
        '  "must_have": list of hard requirements as short lowercase tokens.\n'
        '  "nice_to_have": list of preferences (e.g. "ideally ...").\n'
        '  "avoid": list of dealbreakers to exclude (e.g. "no lift", "basement").\n'
        '  "commute_to": a single place/station the tenant commutes to, else "".\n'
        "Rules: an orientation like \"south facing\" is a feature token. An EPC floor "
        'must be the token "epc <letter> or better" (e.g. "epc c or better"). Put '
        '"no X"/"without X" requirements in avoid, not must_have. Use [] when none apply.\n'
        f"TEXT: {text}"
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=400,
        )
        raw = resp.choices[0].message.content
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        d = json.loads(raw)
        return Brief(id=bid, text=text, max_price=d.get("max_price"),
                     min_beds=int(d.get("min_beds") or 0), areas=d.get("areas", []),
                     must_have=d.get("must_have", []), nice_to_have=d.get("nice_to_have", []),
                     avoid=d.get("avoid", []), commute_to=d.get("commute_to", "") or "")
    except Exception as e:
        print(f"[brief llm] {e!r}")
        return None
