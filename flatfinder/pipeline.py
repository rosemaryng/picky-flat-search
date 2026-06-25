"""The core 'hands off' loop: collect -> dedupe -> enrich -> score -> draft -> store.

This is what Modal runs on a schedule. It returns the new matches it produced.
"""
from .collectors import collect_all
from .enquiry import draft_enquiry
from .enrich import enrich
from .models import Brief, Match
from .scoring import score
from .store import get_store


def run_scan(briefs: list[Brief], max_price: int = 2500, min_beds: int = 1,
             min_score: float = 60.0, enrich_top: int = 25, store=None) -> list[Match]:
    store = store or get_store()
    for b in briefs:
        store.upsert_brief(b.to_dict())

    listings = collect_all(max_price=max_price, min_beds=min_beds)
    new = [lst for lst in listings if not store.seen(lst.id)]
    print(f"[scan] {len(listings)} pulled, {len(new)} new")

    # enrich only the freshest few (enrichment hits external APIs)
    for lst in new[:enrich_top]:
        enrich(lst)
    for lst in new:
        store.upsert_listing(lst.to_dict())

    produced: list[Match] = []
    for lst in new:
        for b in briefs:
            sc, reasons = score(lst, b)
            if sc >= min_score:
                m = Match(brief_id=b.id, listing=lst, score=sc, reasons=reasons,
                          status="drafted")
                m.enquiry_draft = draft_enquiry(lst, b)
                store.add_match(m.to_dict())
                produced.append(m)
    produced.sort(key=lambda m: -m.score)
    print(f"[scan] {len(produced)} matches >= {min_score}")
    return produced


def demo_brief() -> Brief:
    return Brief(
        id="brief-demo",
        text=("Looking for an area in Paddington or Farringdon. A cute white-fronted house "
              "or a charming period conversion, larger than 35 square meters. Must be a "
              "quick hop to the Tube (under 10 mins walk) and close to a grocery store for "
              "my morning seeds (under 5 mins walk). Bonus points for high ceilings and "
              "lots of natural light!"),
        max_price=3200,
        min_beds=1,
        areas=["Paddington", "Farringdon"],
        must_have=["period", "supermarket"],
        nice_to_have=["high ceilings", "natural light", "south-facing", "gym"],
        avoid=[],
        contact_name="Rosemary", contact_email="rosemary@example.com",
        contact_phone="07700 900123",
    )
