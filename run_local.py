"""Run the whole pipeline once, locally, with no API keys required.

    python run_local.py

Pulls real London listings, enriches + scores them against a demo brief, drafts
enquiries, and prints the shortlist. Results are also saved to local_db.json and
served by the dashboard (`python -m web.app`).
"""
from flatfinder.pipeline import demo_brief, run_scan
from flatfinder.store import get_store


def main():
    store = get_store()
    brief = demo_brief()
    print(f"Brief: {brief.text}\n")
    print(f"Parsed -> max_price={brief.max_price}, beds>={brief.min_beds}, "
          f"areas={brief.areas}, must={brief.must_have}, nice={brief.nice_to_have}, "
          f"avoid={brief.avoid}\n")

    matches = run_scan([brief], max_price=brief.max_price or 2500,
                       min_beds=brief.min_beds or 1, min_score=55,
                       enrich_top=6, store=store)

    print("\n================ TOP MATCHES ================\n")
    for m in matches[:10]:
        lst = m.listing
        print(f"[{m.score:5.1f}] {lst.source:11} £{lst.price}  {lst.beds}bed  {lst.address[:48]}")
        extra = []
        if lst.sqm:
            extra.append(f"{lst.sqm:.0f}sqm")
        if lst.epc:
            extra.append(f"EPC {lst.epc}")
        if lst.has_lift is not None:
            extra.append("lift" if lst.has_lift else "no lift")
        if lst.transport.get("walk_min") is not None:
            extra.append(f"{lst.transport['walk_min']}min to {lst.transport.get('nearest_station')}")
        if extra:
            print(f"        {' | '.join(extra)}")
        print(f"        why: {', '.join(m.reasons[:6])}")
        print(f"        {lst.url}")
        print()

    print("Stats:", store.stats())
    print("\nNext: `python -m web.app` for the dashboard, or deploy the loop with "
          "`modal deploy app_modal.py`.")


if __name__ == "__main__":
    main()
