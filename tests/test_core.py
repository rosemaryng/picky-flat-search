"""Offline unit tests — no network or API keys needed."""
from flatfinder.brief import parse
from flatfinder.collectors.base import extract_balanced, guess_postcode
from flatfinder.models import Listing
from flatfinder.scoring import _rule_score


def test_extract_balanced_array():
    html = 'junk "properties":[{"a":1},{"b":[2,3]}] more'
    out = extract_balanced(html, '"properties":')
    assert out == '[{"a":1},{"b":[2,3]}]'


def test_extract_balanced_handles_strings_with_brackets():
    html = '"x":{"s":"a]b}c","n":1}'
    out = extract_balanced(html, '"x":')
    assert out == '{"s":"a]b}c","n":1}'


def test_guess_postcode():
    assert guess_postcode("Mabley Street, Hackney, London, E9 5JX") == "E9 5JX"
    assert guess_postcode("Somewhere, London, N1") == "N1"


def test_brief_heuristic_parse():
    b = parse("2 bed in Hackney up to £2500, must have lift, avoid basement")
    assert b.min_beds == 2
    assert b.max_price == 2500
    assert "hackney" in b.areas
    assert "lift" in b.must_have
    assert "basement" not in (b.must_have + b.nice_to_have)


def test_rule_score_penalises_over_budget():
    cheap = Listing(id="1", source="t", url="", price=2000, beds=2,
                    address="Hackney", summary="bright modern flat")
    pricey = Listing(id="2", source="t", url="", price=4000, beds=2,
                     address="Hackney", summary="bright modern flat")
    b = parse("2 bed Hackney up to £2500")
    s_cheap, _ = _rule_score(cheap, b)
    s_pricey, _ = _rule_score(pricey, b)
    assert s_cheap > s_pricey


def test_rule_score_rewards_must_have_lift():
    with_lift = Listing(id="1", source="t", url="", price=2000, beds=1,
                        address="Islington", summary="flat with a lift", has_lift=True)
    no_lift = Listing(id="2", source="t", url="", price=2000, beds=1,
                      address="Islington", summary="top floor walk-up", has_lift=False)
    b = parse("1 bed Islington up to £2500 must have lift")
    s_with, _ = _rule_score(with_lift, b)
    s_without, _ = _rule_score(no_lift, b)
    assert s_with > s_without
