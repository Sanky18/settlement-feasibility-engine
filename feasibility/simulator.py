"""Date-by-date ledger simulation — the single source of truth for feasibility.

The solver *proposes* a creditor-payment vector and a fee placement; this module
*verifies* it by walking the full ledger chronologically and emits the output rows.

Conventions (ASSIGNMENT.md §3, §5.10):
  * money is integer cents;
  * on any date, **all credits are applied before all debits**;
  * the running balance must be ``>= 0`` at every date (end-of-day, after debits —
    which is the intra-day minimum since debits only decrease the balance);
  * nothing scheduled may fall on a date *past* the horizon (the horizon is allowed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from feasibility.engine import ScheduleRow  # noqa: F401  (re-exported shape)


@dataclass
class DateBucket:
    """All monetary activity on a single calendar date."""

    credit: int = 0  # drafts + any injected lump / increment (applied first)
    committed_debit: int = 0  # fixed debits from previously-settled debts
    creditor_payment: int = 0
    bank_fee: int = 0
    program_fee: int = 0

    @property
    def net(self) -> int:
        return self.credit - (
            self.committed_debit + self.creditor_payment + self.bank_fee + self.program_fee
        )

    @property
    def is_schedule_row(self) -> bool:
        """A cadence date that carries a creditor payment or program fee."""
        return self.creditor_payment > 0 or self.program_fee > 0


@dataclass
class SimResult:
    feasible: bool
    min_balance: int
    final_balance: int
    schedule: list[ScheduleRow] = field(default_factory=list)
    reason: str = ""


def build_buckets(
    credits: list[tuple[date, int]],
    committed_debits: list[tuple[date, int]],
    creditor_payments: dict[date, int] | None = None,
    bank_fees: dict[date, int] | None = None,
    program_fees: dict[date, int] | None = None,
) -> dict[date, DateBucket]:
    """Aggregate every event onto its date."""
    buckets: dict[date, DateBucket] = {}

    def b(d: date) -> DateBucket:
        return buckets.setdefault(d, DateBucket())

    for d, amt in credits:
        b(d).credit += amt
    for d, amt in committed_debits:
        b(d).committed_debit += amt
    for d, amt in (creditor_payments or {}).items():
        b(d).creditor_payment += amt
    for d, amt in (bank_fees or {}).items():
        b(d).bank_fee += amt
    for d, amt in (program_fees or {}).items():
        b(d).program_fee += amt
    return buckets


def simulate(
    start_balance: int,
    buckets: dict[date, DateBucket],
    horizon: date,
) -> SimResult:
    """Walk the buckets in date order, returning feasibility + schedule rows."""
    running = start_balance
    min_balance = start_balance
    rows: list[ScheduleRow] = []

    for d in sorted(buckets):
        bucket = buckets[d]
        # A scheduled outflow may never land past the horizon.
        if d > horizon and (
            bucket.creditor_payment or bucket.bank_fee or bucket.program_fee
        ):
            return SimResult(
                feasible=False,
                min_balance=min_balance,
                final_balance=running,
                reason=f"scheduled activity on {d} is past horizon {horizon}",
            )
        running += bucket.net  # credits-before-debits => end-of-day balance
        min_balance = min(min_balance, running)
        if bucket.is_schedule_row:
            rows.append(
                ScheduleRow(
                    date=d,
                    creditor_payment_cents=bucket.creditor_payment,
                    program_fee_cents=bucket.program_fee,
                    bank_fee_cents=bucket.bank_fee,
                    balance_cents=running,
                )
            )

    feasible = min_balance >= 0
    return SimResult(
        feasible=feasible,
        min_balance=min_balance,
        final_balance=running,
        schedule=rows,
        reason="" if feasible else f"balance went negative (min={min_balance})",
    )
