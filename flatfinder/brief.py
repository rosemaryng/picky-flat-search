"""Turn a free-text wishlist into a structured Brief.

LLM-powered when a key is present; otherwise a keyword heuristic so the demo
works offline.
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
             "north facing", "east facing", "west facing", "separate kitchen",
             "basement", "ground floor", "supermarket", "groceries"]


def parse(text: str, **contact) -> Brief:
    bid = contact.pop("id", "brief-1")
    if has_openai():
        b = _llm_parse(text, bid)
        if b is not None:
            for k, v in contact.items():
                setattr(b, k, v)
            return b
    return _heuristic_parse(text, bid, **contact)


def _heuristic_parse(text: str, bid: str, **contact) -> Brief:
    low = text.lower()
    max_price = None
    m = re.search(r"£?\s*([1-9]\d{2,4})\s*(?:pcm|pm|/mo|per month|a month|budget|max)?", low)
    # prefer an explicit budget phrase
    m2 = re.search(r"(?:under|max|budget|up to|<=?)\s*£?\s*([1-9]\d{2,4})", low)
    if m2:
        max_price = int(m2.group(1))
    elif m:
        max_price = int(m.group(1))
    beds = 0
    mb = re.search(r"(\d)\s*(?:\+)?\s*(?:bed|bedroom)", low)
    if mb:
        beds = int(mb.group(1))
    areas = [a for a in _LONDON_AREAS if a in low]
    must, nice, avoid = [], [], []
    for f in _FEATURES:
        if f not in low:
            continue
        # classify by the words in a small window *before* the feature
        idx = low.find(f)
        before = low[max(0, idx - 24):idx]
        if re.search(r"\b(no|avoid|without|not?)\b", before) or f in ("basement", "ground floor", "no lift"):
            avoid.append(f)
        elif re.search(r"\b(must|need|require|essential)\b", before):
            must.append(f)
        else:
            nice.append(f)
    commute = ""
    mc = re.search(r"(?:to|near|close to)\s+([a-z ]{3,20}?)(?:,|\.|$| station| tube)", low)
    if mc:
        commute = mc.group(1).strip()
    b = Brief(id=bid, text=text, max_price=max_price, min_beds=beds, areas=areas,
              must_have=must, nice_to_have=nice, avoid=avoid, commute_to=commute)
    for k, v in contact.items():
        setattr(b, k, v)
    return b


def _llm_parse(text: str, bid: str):
    try:
        from openai import OpenAI
    except Exception:
        return None
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "Extract a structured rental brief from this text. Return strict JSON with keys: "
        "max_price (int pcm or null), min_beds (int), areas (list of London area names), "
        "must_have (list), nice_to_have (list), avoid (list), commute_to (string or '').\n"
        f"TEXT: {text}"
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}], max_tokens=300)
        raw = resp.choices[0].message.content
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        d = json.loads(raw)
        return Brief(id=bid, text=text, max_price=d.get("max_price"),
                     min_beds=int(d.get("min_beds") or 0), areas=d.get("areas", []),
                     must_have=d.get("must_have", []), nice_to_have=d.get("nice_to_have", []),
                     avoid=d.get("avoid", []), commute_to=d.get("commute_to", ""))
    except Exception as e:
        print(f"[brief llm] {e!r}")
        return None
