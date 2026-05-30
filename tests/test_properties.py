"""Property/edge tests: invariants hold across a battery of synthetic cases, plus
specific edge cases (default first_payment_date, EOM cadence, rounding)."""

from __future__ import annotations

from datetime import date

import pytest

from feasibility.cadence import first_payment_date
from feasibility.engine import evaluate_offer
from feasibility.models import Offer, default_first_payment_date
from feasibility.rounding import offer_total_cents, program_fee_total_cents, round_half_up
from feasibility.verify import verify_schedule
from helpers import make_client, make_offer, make_rules


# A grid of synthetic scenarios across all three shapes.
SCENARIOS = []
for shape_kwargs in (
    {"even_pays": True, "max_segments": 1},
    {"ballooning": True, "max_segments": 4},
    {"max_segments": 2, "tiers": [(4, 5000)]},
    {"max_segments": 3},
):
    for settlement in (0.3, 0.5, 0.75):
        for fee_pct in (0.0, 0.1, 0.2):
            SCENARIOS.append((shape_kwargs, settlement, fee_pct))


@pytest.mark.parametrize("shape_kwargs,settlement,fee_pct", SCENARIOS)
def test_feasible_results_satisfy_all_constraints(shape_kwargs, settlement, fee_pct):
    client = make_client(draft=15000, n_drafts=10)
    offer = make_offer(creditor_balance=120000, original_balance=120000, settlement_pct=settlement)
    rules = make_rules(
        min_payment=2500, max_token_pays=4, max_payments=8, max_terms=8,
        bank_fee=300, program_fee_pct=fee_pct, **shape_kwargs,
    )
    r = evaluate_offer(client, offer, rules)
    if r.feasible:
        assert verify_schedule(client, offer, rules, r) == []
    else:
        # Infeasible verdicts must always report both minima.
        assert r.additional_funds is not None
        assert r.additional_funds.lump_sum is not None
        assert r.additional_funds.monthly_increment is not None


def test_default_first_payment_date_is_eom():
    client = make_client(draft=20000, n_drafts=6, first=date(2026, 1, 1))
    offer = Offer("X", 100000, 120000, 0.5, first_payment_date=None)
    assert first_payment_date(client, offer) == default_first_payment_date(client)
    assert first_payment_date(client, offer) == date(2026, 1, 31)
    # And the engine still produces a valid schedule with the default cadence.
    rules = make_rules(even_pays=True, max_payments=6, max_terms=6, program_fee_pct=0.2)
    r = evaluate_offer(client, offer, rules)
    if r.feasible:
        assert verify_schedule(client, offer, rules, r) == []


def test_eom_cadence_handles_february():
    # Jan 31 first payment -> Feb 28 -> Mar 31 ... (true EOM cadence).
    client = make_client(draft=30000, n_drafts=6)
    offer = make_offer(creditor_balance=60000, original_balance=60000, settlement_pct=0.5,
                       first_payment=date(2026, 1, 31))
    rules = make_rules(even_pays=True, max_payments=6, max_terms=6, program_fee_pct=0.1)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible
    assert r.schedule[1].date == date(2026, 2, 28)


def test_round_half_up_explicit():
    assert round_half_up(2.5) == 3
    assert round_half_up(3.5) == 4  # not banker's rounding (would give 4 here anyway)
    assert round_half_up(2.45) == 2
    assert offer_total_cents(0.5, 12345) == 6173  # 6172.5 -> 6173 (half up)
    assert program_fee_total_cents(0.25, 12346) == 3087  # 3086.5 -> 3087


def test_single_payment_k1():
    client = make_client(draft=100000, n_drafts=3)
    offer = make_offer(creditor_balance=40000, original_balance=40000, settlement_pct=0.5)
    rules = make_rules(min_payment=2500, max_payments=1, max_terms=1, max_segments=1)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible
    payments = [row.creditor_payment_cents for row in r.schedule if row.creditor_payment_cents]
    assert payments == [20000]  # one payment = offer_total
