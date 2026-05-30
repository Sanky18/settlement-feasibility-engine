"""Tests for the date-by-date simulator: same-day ordering, zero balance, horizon."""

from __future__ import annotations

from datetime import date

from feasibility.simulator import build_buckets, simulate


def test_credits_before_debits_same_day():
    # On the same date a credit must be applied before a debit; with credit first
    # the day ends at exactly 0 (feasible). The reverse ordering would dip negative
    # mid-day, but our end-of-day rule (credits first) makes it feasible.
    d = date(2026, 1, 31)
    buckets = build_buckets(
        credits=[(d, 1000)],
        committed_debits=[(d, 1000)],
    )
    sim = simulate(0, buckets, horizon=date(2026, 12, 1))
    assert sim.feasible
    assert sim.final_balance == 0


def test_balance_exactly_zero_is_feasible():
    d = date(2026, 1, 31)
    buckets = build_buckets(
        credits=[(date(2026, 1, 1), 2000)],
        committed_debits=[],
        creditor_payments={d: 1500},
        bank_fees={d: 500},
    )
    sim = simulate(0, buckets, horizon=date(2026, 7, 1))
    assert sim.feasible and sim.min_balance == 0


def test_negative_balance_is_infeasible():
    d = date(2026, 1, 31)
    buckets = build_buckets(
        credits=[(date(2026, 1, 1), 1000)],
        committed_debits=[],
        creditor_payments={d: 1500},
    )
    sim = simulate(0, buckets, horizon=date(2026, 7, 1))
    assert not sim.feasible and sim.min_balance < 0


def test_activity_past_horizon_rejected():
    past = date(2026, 8, 1)
    buckets = build_buckets(
        credits=[(date(2026, 1, 1), 100000)],
        committed_debits=[],
        creditor_payments={past: 1000},
    )
    sim = simulate(0, buckets, horizon=date(2026, 7, 1))
    assert not sim.feasible and "horizon" in sim.reason


def test_horizon_date_itself_allowed():
    h = date(2026, 7, 1)
    buckets = build_buckets(
        credits=[(date(2026, 1, 1), 5000)],
        committed_debits=[],
        creditor_payments={h: 1000},
    )
    sim = simulate(0, buckets, horizon=h)
    assert sim.feasible
