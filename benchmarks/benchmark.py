"""Benchmark & profiling harness for the settlement engine.

Run:  python benchmarks/benchmark.py            # tables to stdout
      python benchmarks/benchmark.py --profile  # also dump cProfile hotspots

Produces: per-case timing, binary-search-vs-linear-scan minima, a scaling study
over horizon length, and a greedy-vs-brute-force correctness cross-check. Results
are written to benchmarks/results/latest.json.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from datetime import date
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from feasibility.engine import evaluate_offer  # noqa: E402
from feasibility.models import (  # noqa: E402
    Client,
    CreditorRules,
    LedgerEntry,
    Offer,
    add_months,
    load_case,
)
from feasibility.solver import solve  # noqa: E402


# --------------------------------------------------------------------------- #
# Synthetic case builder (no test deps)
# --------------------------------------------------------------------------- #

def synth_case(n_drafts: int, max_payments: int, settlement: float = 0.3,
               draft: int = 10000, fee_pct: float = 0.2) -> tuple[Client, Offer, CreditorRules]:
    first = date(2026, 1, 1)
    dates = [add_months(first, i) for i in range(n_drafts)]
    client = Client(
        draft_amount_cents=draft, draft_day=1, first_draft_date=dates[0],
        last_draft_date=dates[-1], as_of_date=date(2025, 12, 31), current_balance_cents=0,
        ledger=[LedgerEntry(d, draft, "credit") for d in dates],
    )
    # Creditor balance set so offer_total + fee stays well under total inflow -> the
    # case is feasible, so the scaling study times the Part-1 solver (not the minima).
    bal = draft * n_drafts
    offer = Offer("Synth", bal, bal, settlement, first_payment_date=date(2026, 1, 31))
    rules = CreditorRules(
        max_terms=max_payments, max_payments=max_payments, min_payment_cents=2500,
        max_token_pays=max_payments // 2, min_payment_tiers=[(max_payments // 2 + 1, 5000)],
        even_pays=False, is_ballooning_allowed=False, max_segments=2,
        bank_fee_cents=500, program_fee_pct=fee_pct,
    )
    return client, offer, rules


def _time(fn, repeats: int) -> float:
    """Mean wall-clock milliseconds over ``repeats`` runs (best-of-3 batches)."""
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        for _ in range(repeats):
            fn()
        best = min(best, (time.perf_counter() - t0) / repeats * 1000)
    return best


# --------------------------------------------------------------------------- #
# Benchmarks
# --------------------------------------------------------------------------- #

def bench_cases() -> list[dict]:
    rows = []
    for case in ["case1_feasible_even", "case2_infeasible_minima", "case3_balloon", "case4_tiers"]:
        c, o, r = load_case(str(ROOT / "cases" / case))
        ms = _time(lambda: evaluate_offer(c, o, r), repeats=200)
        res = evaluate_offer(c, o, r)
        rows.append({"case": case, "ms": round(ms, 4),
                     "feasible": res.feasible, "shape": res.pay_shape_used})
    return rows


def _linear_min_lump(client, offer, rules, d) -> int:
    L = 0
    while not solve(client, offer, rules, extra_credits=[(d, L)]).feasible:
        L += 1
    return L


def bench_minima_search() -> dict:
    from feasibility.minima import minimum_additional_funds

    c, o, r = load_case(str(ROOT / "cases" / "case2_infeasible_minima"))
    d = sorted(e.date for e in c.ledger if e.type == "credit")[0]
    binary_ms = _time(lambda: minimum_additional_funds(c, o, r), repeats=50)
    # Linear scan is intentionally expensive (one solve per cent); measure once.
    t0 = time.perf_counter()
    _linear_min_lump(c, o, r, d)
    linear_ms = (time.perf_counter() - t0) * 1000
    return {"binary_ms": round(binary_ms, 4), "linear_lump_ms": round(linear_ms, 4),
            "speedup": round(linear_ms / binary_ms, 1) if binary_ms else None}


def bench_scaling() -> list[dict]:
    rows = []
    for n in [6, 12, 24, 48, 96]:
        c, o, r = synth_case(n_drafts=n, max_payments=n)  # feasible -> Part-1 solver only
        assert evaluate_offer(c, o, r).feasible, f"scaling case n={n} unexpectedly infeasible"
        ms = _time(lambda: evaluate_offer(c, o, r), repeats=max(5, 200 // n))
        rows.append({"cadence_dates": n, "max_k": n, "ms": round(ms, 4)})
    return rows


def bench_correctness_oracle() -> dict:
    """Greedy solver vs brute-force optimum on a battery of tiny cases."""
    sys.path.insert(0, str(ROOT / "tests"))
    from helpers import (  # type: ignore
        brute_best_fee_vector, make_client, make_offer, make_rules, solver_fee_vector,
    )

    checked = agreed = 0
    for settlement in (0.2, 0.3, 0.4):
        for seg in (1, 2, 3):
            client = make_client(draft=200, n_drafts=8)
            offer = make_offer(creditor_balance=500, original_balance=500, settlement_pct=settlement)
            rules = make_rules(min_payment=25, max_token_pays=3, max_payments=4, max_terms=4,
                               max_segments=seg, bank_fee=0, program_fee_pct=0.05)
            res = evaluate_offer(client, offer, rules)
            if not res.feasible:
                continue
            best, eligible = brute_best_fee_vector(client, offer, rules)
            checked += 1
            if best is not None and solver_fee_vector(res, eligible) == best:
                agreed += 1
    return {"cases_checked": checked, "matched_optimum": agreed}


def profile_hotspots() -> str:
    c, o, r = synth_case(n_drafts=96, max_payments=48)
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(50):
        evaluate_offer(c, o, r)
    pr.disable()
    buf = StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(12)
    return buf.getvalue()


def _table(rows: list[dict]) -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0])
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", action="store_true", help="also dump cProfile hotspots")
    args = ap.parse_args()

    cases = bench_cases()
    minima = bench_minima_search()
    scaling = bench_scaling()
    oracle = bench_correctness_oracle()

    print("\n## Per-case timing (mean ms, best of 3 batches)\n")
    print(_table(cases))
    print("\n## Minimum-funds search: binary vs linear scan\n")
    print(_table([minima]))
    print("\n## Scaling study (synthetic staircase, solver wall-clock)\n")
    print(_table(scaling))
    print("\n## Correctness: greedy vs brute-force optimum\n")
    print(_table([oracle]))

    results = {"cases": cases, "minima": minima, "scaling": scaling, "oracle": oracle}
    out_dir = ROOT / "benchmarks" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_dir / 'latest.json'}")

    if args.profile:
        print("\n## cProfile hotspots (n_drafts=96, k<=48, x50)\n")
        print("```\n" + profile_hotspots() + "```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
