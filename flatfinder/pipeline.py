"""The core 'hands off' loop: collect -> dedupe -> enrich -> score -> draft -> store.

This is what Modal runs on a schedule. It returns the new matches it produced.
"""
from .brief import parse as parse_brief
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
    return parse_brief(
        "1 or 2 bed flat in East London (Hackney, Islington, Clapton or London Fields), "
        "budget up to £2500 pcm, must have a lift, ideally south facing and bright, "
        "EPC C or better, close to a tube/overground (under 10 min walk), gym and "
        "supermarket nearby. Avoid basement and ground floor.",
        id="brief-demo",
        contact_name="Rosemary", contact_email="rosemary@example.com",
        contact_phone="07700 900123",
    )
