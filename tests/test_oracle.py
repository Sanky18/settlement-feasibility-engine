"""Brute-force optimality cross-check: the constructive solver must achieve the
maximum fee-earliness over *every* valid vector of the chosen shape.

Totals are kept tiny (the brute-force vector enumeration is exponential in
``offer_total / min_payment``) and evenly divisible, so the strict segment
definition coincides with the solver's. The optimality claim is scale-independent.
"""

from __future__ import annotations

from feasibility.engine import evaluate_offer
from helpers import (
    brute_best_fee_vector,
    make_client,
    make_offer,
    make_rules,
    solver_fee_vector,
)


def _assert_optimal(client, offer, rules):
    r = evaluate_offer(client, offer, rules)
    assert r.feasible, "expected a feasible case for the oracle comparison"
    best, eligible = brute_best_fee_vector(client, offer, rules)
    assert best is not None
    got = solver_fee_vector(r, eligible)
    assert got == best, f"solver fee-earliness {got} != brute-force optimum {best}"


def test_oracle_staircase():
    # offer_total = round(0.3 * 1000) = 300; fee = round(0.05 * 1000) = 50.
    client = make_client(draft=200, n_drafts=8)
    offer = make_offer(creditor_balance=1000, original_balance=1000, settlement_pct=0.3)
    rules = make_rules(
        min_payment=25, max_token_pays=3, max_payments=6, max_terms=6,
        max_segments=2, bank_fee=0, program_fee_pct=0.05,
    )
    _assert_optimal(client, offer, rules)


def test_oracle_balloon():
    # offer_total = 150; fee = 0; ballooning allowed (segments unbounded, so the
    # enumeration is large — kept small with total 150 and k <= 4).
    client = make_client(draft=150, n_drafts=7)
    offer = make_offer(creditor_balance=300, original_balance=300, settlement_pct=0.5)
    rules = make_rules(
        min_payment=25, max_token_pays=4, max_payments=4, max_terms=4,
        ballooning=True, bank_fee=0, program_fee_pct=0.0,
    )
    _assert_optimal(client, offer, rules)


def test_oracle_staircase_with_bank_fee_and_tier():
    # offer_total = 300; fee = 30; tier raises the floor from payment 4.
    client = make_client(draft=200, n_drafts=8)
    offer = make_offer(creditor_balance=750, original_balance=1000, settlement_pct=0.4)
    rules = make_rules(
        min_payment=25, max_token_pays=3, tiers=[(4, 50)], max_payments=6, max_terms=6,
        max_segments=2, bank_fee=5, program_fee_pct=0.03,
    )
    _assert_optimal(client, offer, rules)
