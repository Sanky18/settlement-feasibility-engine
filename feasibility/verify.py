"""Independent end-to-end validator for a produced schedule.

Re-derives the full ledger from the *raw inputs* plus the schedule rows and checks
every hard constraint in ASSIGNMENT.md §5. It deliberately shares no state with the
solver, so it is a genuine cross-check (used heavily in the test suite). Returns a
list of human-readable violations; an empty list means the schedule is valid.
"""

from __future__ import annotations

from feasibility.cadence import cadence_dates, cadence_dates_until, first_payment_date, horizon
from feasibility.engine import Result
from feasibility.models import Client, CreditorRules, Offer
from feasibility.rounding import offer_total_cents, program_fee_total_cents
from feasibility.shapes import floor_vector
from feasibility.simulator import build_buckets, simulate


def verify_schedule(client: Client, offer: Offer, rules: CreditorRules, result: Result) -> list[str]:
    problems: list[str] = []
    if not result.feasible or result.schedule is None:
        return ["result is not feasible / has no schedule"]

    rows = result.schedule
    offer_total = offer_total_cents(offer.settlement_pct, offer.current_balance_cents)
    total_fee = program_fee_total_cents(rules.program_fee_pct, offer.original_balance_cents)
    fpd = first_payment_date(client, offer)
    hor = horizon(client)
    k_cap = min(rules.max_payments, rules.max_terms)

    pay_rows = [r for r in rows if r.creditor_payment_cents > 0]
    payments = [r.creditor_payment_cents for r in pay_rows]
    k = len(payments)

    # 1. Count & placement: consecutive cadence dates from the first payment date.
    if not (1 <= k <= k_cap):
        problems.append(f"payment count {k} not in [1, {k_cap}]")
    expected_dates = cadence_dates(fpd, k)
    actual_dates = [r.date for r in pay_rows]
    if actual_dates != expected_dates:
        problems.append(f"payment dates {actual_dates} != consecutive cadence {expected_dates}")

    # 2. Exact sum.
    if sum(payments) != offer_total:
        problems.append(f"creditor payments sum {sum(payments)} != offer_total {offer_total}")

    # 3. Non-decreasing.
    if any(b < a for a, b in zip(payments, payments[1:])):
        problems.append(f"payments not non-decreasing: {payments}")

    # 4. Floors / token / tiers.
    floors = floor_vector(k, rules)
    for i, (p, f) in enumerate(zip(payments, floors), start=1):
        if p < f:
            problems.append(f"payment {i} = {p} below floor {f}")
    token = sum(1 for p in payments if p == rules.min_payment_cents)
    if token > rules.max_token_pays:
        problems.append(f"{token} token pays exceed max_token_pays {rules.max_token_pays}")
    for frm, min_cents in rules.min_payment_tiers:
        for i, p in enumerate(payments, start=1):
            if i >= frm and p < min_cents:
                problems.append(f"payment {i}={p} below tier floor {min_cents} (from {frm})")

    # 5. Bank fee: on every creditor-payment date, never on a fee-only date.
    for r in rows:
        if r.creditor_payment_cents > 0 and r.bank_fee_cents != rules.bank_fee_cents:
            problems.append(f"{r.date}: bank fee {r.bank_fee_cents} != {rules.bank_fee_cents}")
        if r.creditor_payment_cents == 0 and r.bank_fee_cents != 0:
            problems.append(f"{r.date}: fee-only date charged a bank fee {r.bank_fee_cents}")

    # 6. Program-fee timing: none before the first payment date; fully collected; on cadence.
    fee_rows = [r for r in rows if r.program_fee_cents > 0]
    if sum(r.program_fee_cents for r in rows) != total_fee:
        problems.append(f"program fee total {sum(r.program_fee_cents for r in rows)} != {total_fee}")
    cadence_set = set(cadence_dates_until(fpd, hor))
    for r in fee_rows:
        if r.date < fpd:
            problems.append(f"fee collected on {r.date} before first payment date {fpd}")
        if r.date not in cadence_set:
            problems.append(f"fee collected on non-cadence/over-horizon date {r.date}")

    # 9. Segments (skip for even / balloon, which ignore the cap). A segment boundary
    # is a jump greater than the 1-cent rounding remainder.
    if result.pay_shape_used == "staircase":
        segments = 1 + sum(1 for a, b in zip(payments, payments[1:]) if b - a > 1)
        if segments > rules.max_segments:
            problems.append(f"{segments} segments exceed max_segments {rules.max_segments}")
    if result.pay_shape_used == "even" and len(set(payments)) > 0:
        if max(payments) - min(payments) > 1:
            problems.append(f"even shape but payments vary by >1 cent: {payments}")
    if result.pay_shape_used == "balloon" and not rules.is_ballooning_allowed:
        problems.append("balloon shape used but ballooning not allowed")

    # 10. Feasibility: re-simulate the full ledger from raw inputs.
    problems.extend(_resimulate(client, rows, hor))
    return problems


def _resimulate(client: Client, rows, hor) -> list[str]:
    credits = [(e.date, e.amount_cents) for e in client.ledger
               if e.type == "credit" and e.date > client.as_of_date]
    debits = [(e.date, e.amount_cents) for e in client.ledger
              if e.type == "debit" and e.date > client.as_of_date]
    creditor = {r.date: r.creditor_payment_cents for r in rows if r.creditor_payment_cents}
    bank = {r.date: r.bank_fee_cents for r in rows if r.bank_fee_cents}
    fee = {r.date: r.program_fee_cents for r in rows if r.program_fee_cents}
    buckets = build_buckets(credits, debits, creditor, bank, fee)
    sim = simulate(client.current_balance_cents, buckets, hor)
    out: list[str] = []
    if not sim.feasible:
        out.append(f"re-simulation infeasible: {sim.reason}")
    # The validator's recomputed balances must match the reported row balances.
    by_date = {r.date: r.balance_cents for r in rows}
    for r in sim.schedule:
        if by_date.get(r.date) != r.balance_cents:
            out.append(f"{r.date}: reported balance {by_date.get(r.date)} != recomputed {r.balance_cents}")
    return out
