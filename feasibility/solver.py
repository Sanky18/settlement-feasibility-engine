"""The scheduling solver: pick the payment count and shape that best front-loads fee.

For each candidate count ``k`` (consecutive cadence dates within the horizon) we
build the flag-dictated shape's lexmin creditor vector, verify base feasibility,
place the fee in closed form, and score by fee-earliness. The best feasible
candidate wins; if none is feasible the offer is infeasible (-> Part 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from feasibility.cadence import (
    cadence_dates,
    cadence_dates_until,
    first_payment_date,
    horizon,
    max_cadence_count,
)
from feasibility.engine import ScheduleRow
from feasibility.fee import front_load_fee
from feasibility.models import Client, CreditorRules, Offer
from feasibility.rounding import offer_total_cents, program_fee_total_cents
from feasibility.shapes import build_balloon, build_even, build_staircase
from feasibility.simulator import build_buckets, simulate


@dataclass
class SolveOutcome:
    feasible: bool
    pay_shape_used: str | None = None
    schedule: list[ScheduleRow] | None = None


def chosen_shape(rules: CreditorRules) -> str:
    """Shape precedence: even_pays > is_ballooning_allowed > staircase."""
    if rules.even_pays:
        return "even"
    if rules.is_ballooning_allowed:
        return "balloon"
    return "staircase"


def _build_vector(shape: str, k: int, rules: CreditorRules, offer_total: int):
    if shape == "even":
        return build_even(k, rules, offer_total)
    if shape == "balloon":
        return build_balloon(k, rules, offer_total)
    return build_staircase(k, rules, offer_total)


def _ledger_streams(client: Client) -> tuple[list[tuple[date, int]], list[tuple[date, int]]]:
    """Split the modifiable-future ledger (date > as_of) into credits and debits.

    Entries dated on/before ``as_of_date`` are already baked into
    ``current_balance_cents`` and are NOT re-simulated (ASSIGNMENT.md §3).
    """
    credits, debits = [], []
    for e in client.ledger:
        if e.date <= client.as_of_date:
            continue
        (credits if e.type == "credit" else debits).append((e.date, e.amount_cents))
    return credits, debits


def solve(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    extra_credits: list[tuple[date, int]] | None = None,
) -> SolveOutcome:
    """Return a feasible front-loaded schedule, or ``feasible=False`` if none exists.

    ``extra_credits`` injects additional credits (used by the Part-2 minima search).
    """
    offer_total = offer_total_cents(offer.settlement_pct, offer.current_balance_cents)
    total_fee = program_fee_total_cents(rules.program_fee_pct, offer.original_balance_cents)
    fpd = first_payment_date(client, offer)
    hor = horizon(client)
    start_balance = client.current_balance_cents

    credits, committed_debits = _ledger_streams(client)
    if extra_credits:
        credits = credits + list(extra_credits)

    shape = chosen_shape(rules)
    k_cap = min(rules.max_payments, rules.max_terms)
    max_k = max_cadence_count(fpd, hor, k_cap)
    eligible_fee_dates = cadence_dates_until(fpd, hor)

    best_key = None
    best_schedule: list[ScheduleRow] | None = None

    for k in range(1, max_k + 1):
        vec = _build_vector(shape, k, rules, offer_total)
        if vec is None or sum(vec) != offer_total:
            continue

        pay_dates = cadence_dates(fpd, k)
        creditor_payments = {d: amt for d, amt in zip(pay_dates, vec)}
        # Bank fee on each date carrying a creditor payment (never on a fee-only date).
        bank_fees = {d: rules.bank_fee_cents for d in pay_dates if rules.bank_fee_cents}

        no_fee_buckets = build_buckets(credits, committed_debits, creditor_payments, bank_fees)
        if not simulate(start_balance, no_fee_buckets, hor).feasible:
            continue

        fees, fully = front_load_fee(start_balance, no_fee_buckets, eligible_fee_dates, total_fee)
        if not fully:
            continue

        full_buckets = build_buckets(
            credits, committed_debits, creditor_payments, bank_fees, fees
        )
        sim = simulate(start_balance, full_buckets, hor)
        if not sim.feasible:
            continue

        # Objective: maximize fee collected earliest (lexicographic over cadence
        # dates); tie-break toward fewer payments (smaller k = simpler, less bank fee).
        fee_vector = tuple(fees.get(d, 0) for d in eligible_fee_dates)
        key = (fee_vector, -k)
        if best_key is None or key > best_key:
            best_key = key
            best_schedule = sim.schedule

    if best_schedule is None:
        return SolveOutcome(feasible=False)
    return SolveOutcome(feasible=True, pay_shape_used=shape, schedule=best_schedule)
