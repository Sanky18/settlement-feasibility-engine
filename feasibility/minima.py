"""Part 2 — minimum additional funding when an offer is infeasible.

Feasibility is **monotone** in money: adding cash never makes a feasible offer
infeasible. So the smallest lump sum and the smallest uniform monthly increment are
each found by binary search over the solver's feasibility predicate. Guardrails
from §8 are applied afterward.
"""

from __future__ import annotations

from datetime import date

from feasibility.engine import AdditionalFunds, FundsOption
from feasibility.models import Client, CreditorRules, Offer
from feasibility.rounding import offer_total_cents, program_fee_total_cents, round_half_up
from feasibility.solver import solve


def _future_draft_dates(client: Client) -> list[date]:
    """Draft credit dates after ``as_of`` — the ones a monthly increment touches."""
    return [e.date for e in client.ledger if e.type == "credit" and e.date > client.as_of_date]


def _lump_date(client: Client) -> date:
    """Earliest modifiable date to drop a lump on (earlier is weakly more useful)."""
    future = sorted(_future_draft_dates(client))
    return future[0] if future else client.first_draft_date


def _smallest_feasible(predicate, hi: int) -> int | None:
    """Smallest non-negative ``v`` in [0, hi] with ``predicate(v)`` true, else None."""
    if not predicate(hi):
        return None
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if predicate(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def _funding_upper_bound(offer: Offer, rules: CreditorRules) -> int:
    offer_total = offer_total_cents(offer.settlement_pct, offer.current_balance_cents)
    fee = program_fee_total_cents(rules.program_fee_pct, offer.original_balance_cents)
    cap = min(rules.max_payments, rules.max_terms)
    # Enough cash, dropped early, to cover every obligation immediately.
    return offer_total + fee + rules.bank_fee_cents * max(cap, 1) + 1


def _lump_option(client: Client, offer: Offer, rules: CreditorRules) -> FundsOption:
    d = _lump_date(client)
    hi = _funding_upper_bound(offer, rules)

    def feasible(L: int) -> bool:
        return solve(client, offer, rules, extra_credits=[(d, L)]).feasible

    amount = _smallest_feasible(feasible, hi)
    if amount is None:
        return FundsOption(amount_cents=hi, within_guardrail=False, reason="no feasible schedule exists at any lump-sum funding", date=d)

    offer_total = offer_total_cents(offer.settlement_pct, offer.current_balance_cents)
    cap = round_half_up(0.65 * offer_total)
    ok = amount <= cap
    reason = "" if ok else f"lump sum {amount} exceeds guardrail {cap} (= round(0.65 * offer_total))"
    return FundsOption(amount_cents=amount, within_guardrail=ok, reason=reason, date=d)


def _increment_option(client: Client, offer: Offer, rules: CreditorRules) -> FundsOption:
    draft_dates = sorted(_future_draft_dates(client))
    n = len(draft_dates)
    hi = _funding_upper_bound(offer, rules)

    def feasible(X: int) -> bool:
        extra = [(d, X) for d in draft_dates]
        return solve(client, offer, rules, extra_credits=extra).feasible

    amount = _smallest_feasible(feasible, hi)
    if amount is None:
        return FundsOption(amount_cents=hi, within_guardrail=False, reason="no feasible schedule exists at any monthly increment", num_drafts=n)

    cap = max(10000, round_half_up(0.40 * client.draft_amount_cents))
    ok = amount <= cap
    reason = "" if ok else f"increment {amount} exceeds guardrail {cap} (= max(10000, round(0.40 * draft)))"
    return FundsOption(amount_cents=amount, within_guardrail=ok, reason=reason, num_drafts=n)


def minimum_additional_funds(client: Client, offer: Offer, rules: CreditorRules) -> AdditionalFunds:
    return AdditionalFunds(
        lump_sum=_lump_option(client, offer, rules),
        monthly_increment=_increment_option(client, offer, rules),
    )
