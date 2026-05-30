"""Program-fee placement — the closed-form front-loading result (design doc §2).

Given a *fixed* creditor schedule (and therefore a fixed pre-fee balance at every
date), the earliest feasible way to collect the total program fee ``F`` is:

    cumulative_fee(d) = min( F, suffix_min_{x >= d} balance_before_fee(x) )

i.e. a single reverse pass. Locking in any more fee by date ``d`` would drive a
later mandatory creditor payment negative; locking in less is strictly worse for
"fee as early as possible". So no search is needed — placement is O(#dates).
"""

from __future__ import annotations

from datetime import date

from feasibility.simulator import DateBucket


def _balances_before_fee(
    start_balance: int,
    no_fee_buckets: dict[date, DateBucket],
    eligible_dates: list[date],
) -> tuple[list[date], dict[date, int]]:
    """End-of-day balance at every relevant date, *before* any program fee."""
    all_dates = sorted(set(no_fee_buckets) | set(eligible_dates))
    balances: dict[date, int] = {}
    running = start_balance
    for d in all_dates:
        if d in no_fee_buckets:
            running += no_fee_buckets[d].net
        balances[d] = running
    return all_dates, balances


def front_load_fee(
    start_balance: int,
    no_fee_buckets: dict[date, DateBucket],
    eligible_dates: list[date],
    total_fee: int,
) -> tuple[dict[date, int], bool]:
    """Place ``total_fee`` as early as possible across ``eligible_dates``.

    ``eligible_dates`` are the cadence dates on/after the first creditor payment and
    on/before the horizon (the only dates a fee may land on, §5.6). Returns the
    per-date fee map and whether the *full* fee could be collected by the horizon.
    """
    if total_fee <= 0:
        return {}, total_fee == 0

    all_dates, balances = _balances_before_fee(start_balance, no_fee_buckets, eligible_dates)

    # Suffix minimum of the pre-fee balance: the most fee we can lock in by date d.
    suffix_min: dict[date, int] = {}
    m = float("inf")
    for d in reversed(all_dates):
        m = min(m, balances[d])
        suffix_min[d] = m

    fees: dict[date, int] = {}
    cumulative = 0
    for d in sorted(eligible_dates):
        cap = min(total_fee, suffix_min[d])  # non-decreasing in d, never below cumulative
        add = cap - cumulative
        if add > 0:
            fees[d] = add
            cumulative = cap
        if cumulative >= total_fee:
            break

    return fees, cumulative == total_fee
