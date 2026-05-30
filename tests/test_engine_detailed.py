"""Detailed assertions on the four provided cases + full constraint verification."""

from __future__ import annotations

from datetime import date

from feasibility.engine import evaluate_offer
from feasibility.models import load_case
from feasibility.verify import verify_schedule


def _run(case: str):
    client, offer, rules = load_case(f"cases/{case}")
    return client, offer, rules, evaluate_offer(client, offer, rules)


def test_case1_even_full_verification():
    client, offer, rules, r = _run("case1_feasible_even")
    assert r.feasible and r.pay_shape_used == "even"
    assert verify_schedule(client, offer, rules, r) == []
    payments = [row.creditor_payment_cents for row in r.schedule]
    assert sum(payments) == 50000
    assert max(payments) - min(payments) <= 1  # equal up to remainder
    # Fee fully front-loaded into the earliest dates.
    assert sum(row.program_fee_cents for row in r.schedule) == 30000
    assert r.schedule[0].program_fee_cents > 0
    assert r.schedule[0].balance_cents == 0  # balance hits exactly $0


def test_case2_infeasible_minima_exact():
    _, _, _, r = _run("case2_infeasible_minima")
    assert r.feasible is False and r.schedule is None
    af = r.additional_funds
    assert af.lump_sum.amount_cents == 10000 and af.lump_sum.within_guardrail
    assert af.monthly_increment.amount_cents == 2500
    assert af.monthly_increment.num_drafts == 5 and af.monthly_increment.within_guardrail


def test_case3_balloon_full_verification():
    client, offer, rules, r = _run("case3_balloon")
    assert r.feasible and r.pay_shape_used == "balloon"
    assert verify_schedule(client, offer, rules, r) == []
    payments = [row.creditor_payment_cents for row in r.schedule]
    assert sum(payments) == 30000
    assert payments[-1] == max(payments)  # final balloon is the largest
    assert payments[-1] > payments[0]


def test_case4_staircase_full_verification():
    client, offer, rules, r = _run("case4_tiers")
    assert r.feasible and r.pay_shape_used == "staircase"
    assert verify_schedule(client, offer, rules, r) == []
    payments = [row.creditor_payment_cents for row in r.schedule if row.creditor_payment_cents > 0]
    assert sum(payments) == 60000
    assert all(p >= 5000 for p in payments[6:])  # tier floor from payment 7
    assert sum(1 for p in payments if p == 2500) <= 6  # token cap
    segments = 1 + sum(1 for a, b in zip(payments, payments[1:]) if b - a > 1)
    assert segments <= 2  # max_segments


def test_all_cases_serialize():
    for case in ["case1_feasible_even", "case2_infeasible_minima", "case3_balloon", "case4_tiers"]:
        _, _, _, r = _run(case)
        d = r.to_dict()
        assert "feasible" in d and "pay_shape_used" in d
