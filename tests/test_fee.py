"""Tests for program-fee front-loading (the suffix-min closed form)."""

from __future__ import annotations

from datetime import date

from feasibility.fee import front_load_fee
from feasibility.simulator import build_buckets


def _dates(*ds):
    return [date(2026, m, d) for m, d in ds]


def test_worked_micro_example_front_loads_fully():
    # ASSIGNMENT §6 worked example: $100 lands before each of 3 dates, start $0,
    # offer_total $250 -> creditor [50,100,100], fee $50, bank $0, flat min $25.
    pay = _dates((1, 31), (2, 28), (3, 31))
    credits = [(date(2026, 1, 1), 10000), (date(2026, 2, 1), 10000), (date(2026, 3, 1), 10000)]
    creditor = {pay[0]: 5000, pay[1]: 10000, pay[2]: 10000}
    no_fee = build_buckets(credits, [], creditor, {})
    fees, fully = front_load_fee(0, no_fee, pay, total_fee=5000)
    assert fully
    assert fees[pay[0]] == 5000  # entire fee on the first date
    assert sum(fees.values()) == 5000


def test_no_fee_before_first_payment_date():
    # Eligible dates start at the first payment date; nothing earlier is offered.
    pay = _dates((2, 28), (3, 31))
    credits = [(date(2026, 1, 1), 10000), (date(2026, 2, 1), 10000), (date(2026, 3, 1), 10000)]
    creditor = {pay[0]: 5000, pay[1]: 5000}
    no_fee = build_buckets(credits, [], creditor, {})
    fees, fully = front_load_fee(0, no_fee, pay, total_fee=4000)
    assert fully
    assert all(d >= pay[0] for d in fees)


def test_fee_held_back_by_future_dip():
    # A big creditor payment on Feb 28 drops the balance to $5; fresh cash arrives
    # in March. The suffix-min must hold most of the fee until after the dip, even
    # though Jan 31 looks flush. Eligible dates include a fee-only month (Mar 31).
    pay = _dates((1, 31), (2, 28))
    eligible = _dates((1, 31), (2, 28), (3, 31))
    credits = [(date(2026, 1, 1), 10000), (date(2026, 3, 1), 5000)]
    creditor = {pay[0]: 2500, pay[1]: 7000}
    no_fee = build_buckets(credits, [], creditor, {})
    # Pre-fee balances: Jan31=7500, Feb28=500, Mar31=5500. suffix-min @Jan31 = 500.
    fees, fully = front_load_fee(0, no_fee, eligible, total_fee=2000)
    assert fully
    assert fees[pay[0]] == 500  # only the future-min slack can be locked in early
    assert fees[eligible[2]] == 1500  # the rest waits for the March cash


def test_fee_not_fully_collectible_when_too_large():
    pay = _dates((1, 31),)
    credits = [(date(2026, 1, 1), 5000)]
    creditor = {pay[0]: 4000}
    no_fee = build_buckets(credits, [], creditor, {})
    fees, fully = front_load_fee(0, no_fee, pay, total_fee=2000)  # only 1000 free
    assert not fully
