"""Cadence-date logic for creditor payments and fees.

The creditor-payment / fee cadence recurs monthly on its own schedule, *independent*
of the draft schedule (ASSIGNMENT.md §3). It starts at ``first_payment_date`` (or the
end-of-month of ``first_draft_date`` when omitted) and either follows true
end-of-month or preserves the day-of-month clamped to month length.
"""

from __future__ import annotations

from datetime import date

from feasibility.models import (
    Client,
    Offer,
    default_first_payment_date,
    monthly_payment_dates,
)


def first_payment_date(client: Client, offer: Offer) -> date:
    """Resolve the first cadence date, defaulting to EOM of the first draft month."""
    if offer.first_payment_date is not None:
        return offer.first_payment_date
    return default_first_payment_date(client)


def horizon(client: Client) -> date:
    """The horizon is ``last_draft_date``; the horizon date itself is allowed."""
    return client.last_draft_date


def cadence_dates(start: date, count: int) -> list[date]:
    """``count`` consecutive monthly cadence dates from ``start`` (EOM-aware)."""
    return monthly_payment_dates(start, count)


def cadence_dates_until(start: date, horizon_date: date, hard_cap: int = 600) -> list[date]:
    """All consecutive cadence dates from ``start`` that are <= the horizon.

    Used for *fee-eligible* dates, which are not bounded by ``max_payments`` (a
    fee-only month may sit past the last creditor payment, §5.6). ``hard_cap`` is a
    safety bound on the loop, far above any realistic horizon length.
    """
    out: list[date] = []
    for d in cadence_dates(start, hard_cap):
        if d > horizon_date:
            break
        out.append(d)
    return out


def max_cadence_count(start: date, horizon_date: date, hard_cap: int) -> int:
    """How many consecutive cadence dates fit on or before the horizon.

    Bounded by ``hard_cap`` ( = min(max_payments, max_terms) ). Cadence dates are
    monotonically non-decreasing, so we count the prefix that stays <= horizon.
    """
    dates = cadence_dates(start, hard_cap)
    n = 0
    for d in dates:
        if d > horizon_date:
            break
        n += 1
    return n
