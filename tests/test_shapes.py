"""Unit tests for floors and the three shape constructors."""

from __future__ import annotations

from feasibility.shapes import (
    _distribute_remainder,
    build_balloon,
    build_even,
    build_staircase,
    floor_vector,
)
from helpers import make_rules


def test_floor_vector_token_then_exceed():
    rules = make_rules(min_payment=2500, max_token_pays=3)
    floors = floor_vector(6, rules)
    assert floors[:3] == [2500, 2500, 2500]  # token slots at base min
    assert all(f >= 2501 for f in floors[3:])  # must strictly exceed afterward


def test_floor_vector_tier_stepup():
    rules = make_rules(min_payment=2500, max_token_pays=6, tiers=[(7, 5000)])
    floors = floor_vector(9, rules)
    assert floors[:6] == [2500] * 6
    assert floors[6:] == [5000, 5000, 5000]  # tier dominates from payment 7


def test_floor_vector_zero_token_pays():
    rules = make_rules(min_payment=2500, max_token_pays=0)
    floors = floor_vector(3, rules)
    assert all(f >= 2501 for f in floors)  # nothing may equal the base min


def test_distribute_remainder_larger_last():
    assert _distribute_remainder(50000, 6) == [8333, 8333, 8333, 8333, 8334, 8334]
    assert _distribute_remainder(100, 4) == [25, 25, 25, 25]
    assert sum(_distribute_remainder(101, 4)) == 101


def test_build_even_respects_floors():
    rules = make_rules(min_payment=2500, max_token_pays=6)
    assert build_even(4, rules, 40000) == [10000, 10000, 10000, 10000]
    # Below floor -> infeasible.
    assert build_even(6, rules, 6000) is None  # 1000 each < 2500


def test_build_balloon_absorbs_remainder():
    rules = make_rules(min_payment=2500, max_token_pays=6, ballooning=True)
    vec = build_balloon(4, rules, 30000)
    assert vec == [2500, 2500, 2500, 22500]
    assert sum(vec) == 30000


def test_build_balloon_non_decreasing_violation():
    # If the "balloon" would be smaller than the floor head, it is invalid.
    rules = make_rules(min_payment=2500, max_token_pays=6, ballooning=True)
    assert build_balloon(4, rules, 9000) is None  # head sums 7500, balloon 1500 < floor


def test_build_staircase_two_segments_lexmin():
    rules = make_rules(min_payment=2500, max_token_pays=6, tiers=[(7, 5000)], max_segments=2)
    vec = build_staircase(10, rules, 60000)
    assert vec == [2500] * 6 + [11250] * 4
    assert sum(vec) == 60000


def test_build_staircase_single_segment_when_capped():
    rules = make_rules(min_payment=2500, max_token_pays=6, max_segments=1)
    vec = build_staircase(4, rules, 40000)
    assert vec == [10000, 10000, 10000, 10000]  # 1 level only
