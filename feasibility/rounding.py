"""Explicit round-half-up arithmetic.

ASSIGNMENT.md §3 requires round-half-up (a ``.5`` always rounds away from zero),
NOT Python's default banker's rounding (round-half-to-even). We implement it via
``decimal`` with ``ROUND_HALF_UP`` so the behavior is exact and unambiguous.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(value: float | int | Decimal) -> int:
    """Round ``value`` to the nearest integer, halves rounding away from zero.

    >>> round_half_up(2.5)
    3
    >>> round_half_up(-2.5)
    -3
    >>> round_half_up(2.4)
    2
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def offer_total_cents(settlement_pct: float, creditor_balance_cents: int) -> int:
    """What we must pay the creditor = round(settlement_pct * creditor_balance)."""
    return round_half_up(Decimal(str(settlement_pct)) * creditor_balance_cents)


def program_fee_total_cents(program_fee_pct: float, original_balance_cents: int) -> int:
    """Total program fee = round(program_fee_pct * original_balance)."""
    return round_half_up(Decimal(str(program_fee_pct)) * original_balance_cents)
