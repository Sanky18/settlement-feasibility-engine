"""Tests for Part 2 minima: tightness of the binary search, agreement with a linear
scan on a tiny case, and the §8 guardrails."""

from __future__ import annotations

from feasibility.minima import minimum_additional_funds
from feasibility.models import load_case
from feasibility.solver import solve
from helpers import make_client, make_offer, make_rules


def _feasible_lump(client, offer, rules, d, L):
    return solve(client, offer, rules, extra_credits=[(d, L)]).feasible


def _feasible_increment(client, offer, rules, dates, X):
    return solve(client, offer, rules, extra_credits=[(d, X) for d in dates]).feasible


def test_case2_lump_minimum_is_tight():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    d = sorted(e.date for e in client.ledger if e.type == "credit")[0]
    af = minimum_additional_funds(client, offer, rules)
    assert af.lump_sum.amount_cents == 10000
    # Tight under monotonicity: feasible at the minimum, infeasible one cent below.
    assert _feasible_lump(client, offer, rules, d, 10000)
    assert not _feasible_lump(client, offer, rules, d, 9999)


def test_case2_increment_minimum_is_tight():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    dates = sorted(e.date for e in client.ledger if e.type == "credit")
    af = minimum_additional_funds(client, offer, rules)
    assert af.monthly_increment.amount_cents == 2500
    assert af.monthly_increment.num_drafts == 5
    assert _feasible_increment(client, offer, rules, dates, 2500)
    assert not _feasible_increment(client, offer, rules, dates, 2499)


def test_binary_search_matches_full_linear_scan_tiny():
    # Tiny infeasible case where a brute 1-cent scan is cheap; both must agree.
    client = make_client(draft=100, n_drafts=4)
    offer = make_offer(creditor_balance=1000, original_balance=1000, settlement_pct=0.5)
    rules = make_rules(min_payment=25, max_payments=4, max_terms=4, max_segments=2)
    d = sorted(e.date for e in client.ledger if e.type == "credit")[0]
    linear = next((L for L in range(0, 2001) if _feasible_lump(client, offer, rules, d, L)), None)
    af = minimum_additional_funds(client, offer, rules)
    assert af.lump_sum.amount_cents == linear


def test_lump_guardrail_rejection():
    # Small offer_total, large required lump -> L > round(0.65 * offer_total).
    client = make_client(draft=1000, n_drafts=3)
    offer = make_offer(creditor_balance=20000, original_balance=20000, settlement_pct=1.0)
    rules = make_rules(min_payment=2500, max_payments=3, max_terms=3, program_fee_pct=0.0)
    af = minimum_additional_funds(client, offer, rules)
    assert af.lump_sum.amount_cents > 13000  # cap = round(0.65 * 20000)
    assert af.lump_sum.within_guardrail is False
    assert "guardrail" in af.lump_sum.reason


def test_increment_guardrail_rejection():
    # Few drafts + large balance force a per-draft increment above the cap.
    client = make_client(draft=1000, n_drafts=3)
    offer = make_offer(creditor_balance=60000, original_balance=60000, settlement_pct=1.0)
    rules = make_rules(min_payment=2500, max_payments=3, max_terms=3, program_fee_pct=0.0)
    af = minimum_additional_funds(client, offer, rules)
    cap = max(10000, round(0.40 * 1000))  # = 10000
    assert af.monthly_increment.amount_cents > cap
    assert af.monthly_increment.within_guardrail is False
    assert "guardrail" in af.monthly_increment.reason
