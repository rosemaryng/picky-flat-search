"""Offline intelligence tests — no network, no OPENAI_API_KEY.

These exercise the deterministic fallbacks for brief parsing, the tri-state
scorer (incl. EPC / orientation / commute) and the floorplan text reader, so the
core matching logic is guaranteed to work with zero API keys.
"""
import os

import pytest

from flatfinder.brief import _heuristic_parse, parse
from flatfinder.enrich.floorplan import _from_text
from flatfinder.models import Listing
from flatfinder.scoring import _epc_meets, _feature_state, _rule_score


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch):
    """Force the offline path regardless of the developer's environment."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("flatfinder.brief.has_openai", lambda: False)
    monkeypatch.setattr("flatfinder.scoring.has_openai", lambda: False)


def _listing(**kw) -> Listing:
    base = dict(id="x", source="t", url="")
    base.update(kw)
    return Listing(**base)


# --------------------------------------------------------------------------- #
# Brief parsing — budgets
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("2 bed up to £2500", 2500),
    ("under £2,500 pcm", 2500),
    ("budget of 3000", 3000),
    ("around £1.5k", 1500),
    ("no more than 2k pcm", 2000),
    ("between £1500 and £2000", 2000),
    ("£500 pw flat", round(500 * 52 / 12)),
])
def test_budget_parsing(text, expected):
    assert parse(text).max_price == expected


def test_budget_absent_is_none():
    assert parse("bright 2 bed in Hackney").max_price is None


# --------------------------------------------------------------------------- #
# Brief parsing — bed ranges
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("1-2 bedroom flat", 1),
    ("2 to 3 bed", 2),
    ("at least 2 beds", 2),
    ("2+ bed", 2),
    ("studio flat", 0),
    ("3 bedroom house", 3),
])
def test_bed_range_parsing(text, expected):
    assert parse(text).min_beds == expected


# --------------------------------------------------------------------------- #
# Brief parsing — areas
# --------------------------------------------------------------------------- #
def test_area_parsing_multiple():
    b = parse("something in Hackney or Clapton near Victoria Park")
    assert {"hackney", "clapton", "victoria park"} <= set(b.areas)


# --------------------------------------------------------------------------- #
# Brief parsing — must / nice / avoid + the 'no lift' edge case
# --------------------------------------------------------------------------- #
def test_no_lift_goes_to_avoid_not_lift():
    b = parse("1 bed Hackney up to £2000, no lift needed")
    assert "no lift" in b.avoid
    assert "lift" not in b.must_have
    assert "lift" not in b.nice_to_have


def test_must_nice_avoid_classification():
    b = parse("must have a balcony, ideally a garden, avoid basement")
    assert "balcony" in b.must_have
    assert "garden" in b.nice_to_have
    assert "basement" in b.avoid


def test_bare_feature_defaults_to_nice():
    b = parse("a flat with a gym")
    assert "gym" in b.nice_to_have
    assert "gym" not in b.must_have


# --------------------------------------------------------------------------- #
# Brief parsing — EPC floor
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "EPC C or better",
    "epc rating of c or above",
    "minimum EPC C",
    "EPC A-C only",
])
def test_epc_floor_parsing(text):
    b = parse(text)
    assert "epc c or better" in (b.must_have + b.nice_to_have)


# --------------------------------------------------------------------------- #
# Brief parsing — orientation
# --------------------------------------------------------------------------- #
def test_south_facing_parsing():
    b = parse("bright flat, ideally south facing")
    assert "south facing" in b.nice_to_have


def test_dual_aspect_parsing():
    b = parse("must be dual aspect")
    assert "dual aspect" in b.must_have


# --------------------------------------------------------------------------- #
# Brief parsing — commute target
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("20 min commute to Bank", "bank"),
    ("near Liverpool Street station", "liverpool street"),
    ("work in Canary Wharf", "canary wharf"),
])
def test_commute_parsing(text, expected):
    assert parse(text).commute_to == expected


def test_offline_parse_does_not_need_api_key():
    # _heuristic_parse must be self-contained and never touch the network
    assert "OPENAI_API_KEY" not in os.environ
    b = _heuristic_parse("2 bed Hackney £2000", "b-1")
    assert b.max_price == 2000 and b.min_beds == 2


# --------------------------------------------------------------------------- #
# Scoring — tri-state feature resolution
# --------------------------------------------------------------------------- #
def test_feature_state_lift_tristate():
    assert _feature_state("lift", _listing(has_lift=True), "") is True
    assert _feature_state("lift", _listing(has_lift=False), "") is False
    assert _feature_state("lift", _listing(), "") is None


def test_epc_meets_helper():
    assert _epc_meets("B", "C") is True
    assert _epc_meets("C", "C") is True
    assert _epc_meets("E", "C") is False
    assert _epc_meets(None, "C") is None


def test_feature_state_epc_requirement():
    req = "epc c or better"
    assert _feature_state(req, _listing(epc="B"), "") is True
    assert _feature_state(req, _listing(epc="E"), "") is False
    assert _feature_state(req, _listing(), "") is None


def test_feature_state_orientation():
    assert _feature_state("south facing", _listing(aspect="south-facing"), "") is True
    assert _feature_state("south facing", _listing(aspect="north-facing"), "") is False
    assert _feature_state("south facing", _listing(), "") is None


# --------------------------------------------------------------------------- #
# Scoring — monotonicity
# --------------------------------------------------------------------------- #
def test_score_monotonic_in_budget():
    b = parse("2 bed Hackney up to £2500")
    cheaper, _ = _rule_score(_listing(price=2000, beds=2, address="Hackney"), b)
    dearer, _ = _rule_score(_listing(price=2400, beds=2, address="Hackney"), b)
    over, _ = _rule_score(_listing(price=4000, beds=2, address="Hackney"), b)
    assert cheaper > dearer > over


def test_score_monotonic_in_must_haves_present():
    """present must-have > unknown > absent, all else equal."""
    b = parse("1 bed Islington up to £2500 must have lift, EPC C or better, south facing")
    present = _listing(price=2000, beds=1, address="Islington",
                       has_lift=True, epc="B", aspect="south-facing")
    unknown = _listing(price=2000, beds=1, address="Islington")
    absent = _listing(price=2000, beds=1, address="Islington",
                      has_lift=False, epc="E", aspect="north-facing")
    s_present, _ = _rule_score(present, b)
    s_unknown, _ = _rule_score(unknown, b)
    s_absent, _ = _rule_score(absent, b)
    assert s_present > s_unknown > s_absent


def test_score_avoid_present_is_penalised():
    b = parse("1 bed Hackney up to £2500, no garden")
    with_garden, _ = _rule_score(
        _listing(price=2000, beds=1, address="Hackney", summary="lovely garden flat"), b)
    without, _ = _rule_score(
        _listing(price=2000, beds=1, address="Hackney", summary="bright flat"), b)
    assert without > with_garden


def test_score_rewards_known_short_commute_walk():
    b = parse("1 bed Hackney up to £2500")
    near = _listing(price=2000, beds=1, address="Hackney",
                    transport={"walk_min": 5, "nearest_station": "Hackney Central"})
    far = _listing(price=2000, beds=1, address="Hackney", transport={"walk_min": 25})
    assert _rule_score(near, b)[0] > _rule_score(far, b)[0]


def test_score_clamped_0_100():
    b = parse("2 bed Hackney up to £2500 must have lift and balcony and parking")
    terrible = _listing(price=9000, beds=0, address="Nowhere",
                        has_lift=False, summary="basement")
    s, _ = _rule_score(terrible, b)
    assert 0 <= s <= 100


# --------------------------------------------------------------------------- #
# Floorplan — offline text reader
# --------------------------------------------------------------------------- #
def test_floorplan_text_reads_sqm():
    li = _listing(summary="Spacious flat, approx 58.3 sq m internal")
    _from_text(li)
    assert li.sqm == pytest.approx(58.3)


def test_floorplan_text_converts_sqft():
    li = _listing(summary="650 sq ft apartment")
    _from_text(li)
    assert li.sqm == pytest.approx(650 * 0.092903, abs=0.2)


def test_floorplan_text_estimates_from_room_dims():
    li = _listing(summary="Living room 5m x 4m, bedroom 3m x 3m")
    _from_text(li)
    assert li.sqm == pytest.approx(29.0)


def test_floorplan_text_reads_lift_and_aspect():
    li = _listing(summary="Top floor, no lift, south-facing balcony")
    _from_text(li)
    assert li.has_lift is False
    assert li.aspect == "south-facing"


def test_floorplan_text_dual_aspect():
    li = _listing(summary="A bright dual-aspect living room")
    _from_text(li)
    assert li.aspect == "dual aspect"
