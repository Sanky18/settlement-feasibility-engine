"""Test helpers: programmatic case builders and an independent brute-force oracle.

The oracle enumerates *every* valid creditor-payment vector (filtered by shape) and
finds the maximum fee-earliness. Cross-checking the constructive solver against it
proves the central claim: the lexmin shape is the front-loading optimum.
"""

from __future__ import annotations

from datetime import date

from feasibility.cadence import (
    cadence_dates_until,
    first_payment_date,
    horizon,
    max_cadence_count,
)
from feasibility.engine import Result
from feasibility.fee import front_load_fee
from feasibility.models import Client, CreditorRules, LedgerEntry, Offer
from feasibility.rounding import offer_total_cents, program_fee_total_cents
from feasibility.shapes import floor_vector
from feasibility.simulator import build_buckets, simulate
from feasibility.solver import chosen_shape


# --------------------------------------------------------------------------- #
# Case builders
# --------------------------------------------------------------------------- #

def make_client(
    *,
    draft: int,
    n_drafts: int,
    first: date = date(2026, 1, 1),
    draft_day: int = 1,
    as_of: date = date(2025, 12, 31),
    start_balance: int = 0,
    extra_debits: list[tuple[date, int]] | None = None,
) -> Client:
    from feasibility.models import add_months

    dates = [add_months(first, i) for i in range(n_drafts)]
    ledger = [LedgerEntry(d, draft, "credit") for d in dates]
    for d, amt in extra_debits or []:
        ledger.append(LedgerEntry(d, amt, "debit"))
    return Client(
        draft_amount_cents=draft,
        draft_day=draft_day,
        first_draft_date=dates[0],
        last_draft_date=dates[-1],
        as_of_date=as_of,
        current_balance_cents=start_balance,
        ledger=ledger,
    )


def make_offer(
    *,
    creditor_balance: int,
    original_balance: int,
    settlement_pct: float,
    first_payment: date | None = date(2026, 1, 31),
    creditor: str = "TestCo",
) -> Offer:
    return Offer(
        creditor=creditor,
        current_balance_cents=creditor_balance,
        original_balance_cents=original_balance,
        settlement_pct=settlement_pct,
        first_payment_date=first_payment,
    )


def make_rules(
    *,
    max_terms: int = 12,
    max_payments: int = 12,
    min_payment: int = 2500,
    max_token_pays: int = 6,
    tiers: list[tuple[int, int]] | None = None,
    even_pays: bool = False,
    ballooning: bool = False,
    max_segments: int = 2,
    bank_fee: int = 0,
    program_fee_pct: float = 0.0,
) -> CreditorRules:
    return CreditorRules(
        max_terms=max_terms,
        max_payments=max_payments,
        min_payment_cents=min_payment,
        max_token_pays=max_token_pays,
        min_payment_tiers=tiers or [],
        even_pays=even_pays,
        is_ballooning_allowed=ballooning,
        max_segments=max_segments,
        bank_fee_cents=bank_fee,
        program_fee_pct=program_fee_pct,
    )


# --------------------------------------------------------------------------- #
# Brute-force oracle
# --------------------------------------------------------------------------- #

def enum_nondecreasing(k: int, floors: list[int], total: int):
    """Yield every non-decreasing length-``k`` vector >= floors summing to ``total``.

    Exponential in ``total / min_floor`` — intended only for tiny oracle cases.
    """
    out: list[tuple[int, ...]] = []

    def rec(i: int, prev: int, remaining: int, acc: list[int]) -> None:
        if i == k:
            if remaining == 0:
                out.append(tuple(acc))
            return
        lo = max(prev, floors[i])
        hi = remaining // (k - i)  # leave enough for the rest (each >= v)
        for v in range(lo, hi + 1):
            acc.append(v)
            rec(i + 1, v, remaining - v, acc)
            acc.pop()

    rec(0, 0, total, [])
    return out


def _segments(vec: tuple[int, ...]) -> int:
    return 1 + sum(1 for a, b in zip(vec, vec[1:]) if b - a > 1)


def _shape_ok(vec: tuple[int, ...], shape: str, rules: CreditorRules) -> bool:
    if shape == "even":
        return max(vec) - min(vec) <= 1
    if shape == "staircase":
        return _segments(vec) <= rules.max_segments
    return True  # balloon: no segment cap


def brute_best_fee_vector(client: Client, offer: Offer, rules: CreditorRules):
    """Max fee-earliness vector over *all* valid vectors of the chosen shape."""
    shape = chosen_shape(rules)
    offer_total = offer_total_cents(offer.settlement_pct, offer.current_balance_cents)
    total_fee = program_fee_total_cents(rules.program_fee_pct, offer.original_balance_cents)
    fpd = first_payment_date(client, offer)
    hor = horizon(client)
    eligible = cadence_dates_until(fpd, hor)
    from feasibility.cadence import cadence_dates

    credits = [(e.date, e.amount_cents) for e in client.ledger
               if e.type == "credit" and e.date > client.as_of_date]
    debits = [(e.date, e.amount_cents) for e in client.ledger
              if e.type == "debit" and e.date > client.as_of_date]

    max_k = max_cadence_count(fpd, hor, min(rules.max_payments, rules.max_terms))
    best = None
    for k in range(1, max_k + 1):
        floors = floor_vector(k, rules)
        pay_dates = cadence_dates(fpd, k)
        for vec in enum_nondecreasing(k, floors, offer_total):
            if not _shape_ok(vec, shape, rules):
                continue
            creditor = {d: a for d, a in zip(pay_dates, vec)}
            bank = {d: rules.bank_fee_cents for d in pay_dates if rules.bank_fee_cents}
            no_fee = build_buckets(credits, debits, creditor, bank)
            if not simulate(client.current_balance_cents, no_fee, hor).feasible:
                continue
            fees, fully = front_load_fee(client.current_balance_cents, no_fee, eligible, total_fee)
            if not fully:
                continue
            full = build_buckets(credits, debits, creditor, bank, fees)
            if not simulate(client.current_balance_cents, full, hor).feasible:
                continue
            fee_vec = tuple(fees.get(d, 0) for d in eligible)
            if best is None or fee_vec > best:
                best = fee_vec
    return best, eligible


def solver_fee_vector(result: Result, eligible: list[date]) -> tuple[int, ...]:
    fees = {r.date: r.program_fee_cents for r in (result.schedule or [])}
    return tuple(fees.get(d, 0) for d in eligible)
