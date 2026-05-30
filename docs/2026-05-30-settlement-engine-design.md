# Design — Settlement Feasibility & Fee Engine

**Date:** 2026-05-30
**Status:** Approved, implementing

## 1. Problem (condensed)

`evaluate_offer(client, offer, rules) -> Result` must, given one escrow account
(SDA) with fixed monthly drafts, decide whether a settlement offer is
**affordable** (running balance never negative, nothing past the horizon) and if
so emit a payment schedule that **collects our program fee as early as possible**.
If not affordable, compute the **minimum extra funding** in two independent forms
(lump sum, monthly increment) with guardrails.

See `ASSIGNMENT.md` for the authoritative specification.

## 2. The key result that makes this tractable

Separate the two cash uses on the account — **creditor payments** (mandatory,
shaped) and **program fee** (ours, fungible) — and the problem decomposes.

Define the **non-fee slack** at each simulation date `d`:

```
S(d) = cumulative_credits(<= d)
     - cumulative( creditor_payments + bank_fees + committed_debits )(<= d)
```

Two facts follow:

1. **Feasibility of a creditor vector** ⟺ `S(d) >= 0` for every date **and**
   total program fee `F <= S(horizon)`. (Credits-before-debits ordering is baked
   into how `S(d)` is evaluated on each date.)

2. **Optimal fee front-loading is closed-form.** The maximum cumulative fee
   collectable *by* date `d` without starving any later mandatory creditor payment
   is

   ```
   CFee(d) = min( F, suffixMin_{d' >= d, d' eligible} S(d') )
   ```

   i.e. a single reverse pass (suffix minimum of slack). Pulling more fee earlier
   than this would drive some future date negative; pulling less is strictly worse
   for the objective. So fee placement needs **no search** — it is O(#dates).

This turns the open-ended objective into a clean optimization: front-loading the
fee ⟺ keeping cumulative creditor outflow **as low as possible early**.

## 3. Payment-shape interpretation (the open-ended crux)

"Fee as early as possible" ⟺ **lexicographically minimize `(p_1, …, p_k)`** subject
to all hard constraints. Each shape is the lexmin under its creditor flag:

- **even** (`even_pays = true`): all payments equal; when `offer_total` is not
  divisible by `k`, the remainder cents are added to the **latest** payments
  (`base = offer_total // k`, last `r` payments get `+1`) so the sequence stays
  non-decreasing. We evaluate every feasible `k` and pick the one whose resulting
  **fee-earliness vector** (fee collected per date, compared lexicographically) is
  best.

- **balloon** (`is_ballooning_allowed = true`): payments `1..k-1` sit at their
  position floors (token-pay slots at the base minimum are consumed first, then
  the strict-exceed / tier floors apply); the **final** payment absorbs the entire
  remaining balance. Balloon obeys its own floor and non-decreasing. We **prefer a
  balloon whenever it is allowed**, because deferring creditor cash to the end is
  exactly what maximizes early free cash for the fee — the balloon dominates a
  staircase for our objective. The balloon is pushed to the **latest feasible**
  cadence date.

- **staircase** (neither flag): lexmin non-decreasing vector restricted to **at
  most `max_segments` distinct payment levels**. Early payments are held at the
  lowest floor-respecting level; level jumps are placed as **late** as possible.
  We enumerate the segment breakpoints (`C(k-1, s-1)`, tiny for `k <= 12`), lexmin
  the level values for each layout, and pick the best by the fee-earliness score.

**Shape precedence:** `even_pays` > `is_ballooning_allowed` > staircase.

### Floors (apply to every shape)

The floor at payment position `i` (1-based) is the **maximum** of:
- base `min_payment_cents`;
- the **token-pay** rule — at most `max_token_pays` payments may *equal* the base
  minimum; once that budget is exhausted, a payment must strictly exceed the base
  minimum (modeled as floor `min_payment_cents + 1` for positions beyond the token
  budget, raised further by the non-decreasing constraint);
- any applicable `min_payment_tiers` step-up (`from_payment_number` onward).

Non-decreasing is enforced as a running max over the position floors.

## 4. Algorithm

```
K_max = min(max_payments, max_terms)
best = None
for k in 1 .. K_max:
    dates = cadence_dates(first_payment_date, k)
    if any(date > horizon): break          # consecutive => later k only worse
    p = build_shape(k, rules)              # even | balloon | staircase lexmin
    if p is None: continue                 # shape infeasible at this k
    S = slack(ledger, p, bank_fees)
    if min(S) < 0 or F > S[horizon]: continue
    fee = front_load_fee(S, F)             # suffix-min closed form
    score = fee_earliness(fee)
    best = argmax(best, score)
if best is None: -> Part 2 (minima)
else: simulate(best) -> schedule rows
```

- **Simulator** is the single source of truth: it builds the full ledger
  (committed entries with date > `as_of` + creditor payments + bank fees +
  program fees), sorts by date with **credits before debits**, walks the running
  balance from `current_balance_cents`, and asserts `>= 0` everywhere and nothing
  scheduled past the horizon. The solver *proposes*; the simulator *verifies* and
  emits the output rows.

- **Part 2 minima** exploit monotonicity (more money never reduces feasibility):
  - **lump sum** `L`: binary-search the smallest `L` such that a single extra
    credit of `L` on the earliest modifiable date (`first_draft_date`) makes the
    offer feasible. Guardrail: reject if `L > round(0.65 * offer_total)`.
  - **monthly increment** `X`: binary-search the smallest uniform `X` added to
    every draft dated after `as_of_date`; `N` = count of those drafts. Guardrail:
    reject if `X > max(10000, round(0.40 * draft_amount_cents))`.

## 5. Module architecture

| Module | Responsibility | Depends on |
|---|---|---|
| `models.py` | dataclasses, loaders, date helpers (provided; loader extended to accept `creditor_balance_cents`) | stdlib |
| `rounding.py` | explicit `round_half_up` | stdlib |
| `cadence.py` | cadence date generation, horizon filtering | models |
| `simulator.py` | ledger build + date-by-date simulation + verification | models, rounding |
| `shapes.py` | floors/token/tier + even/balloon/staircase lexmin constructors | rounding |
| `fee.py` | slack `S(d)` + suffix-min fee front-loading | — |
| `solver.py` | k-loop, shape selection, best-schedule choice | shapes, fee, simulator, cadence |
| `minima.py` | binary-search lump + increment + guardrails | solver, rounding |
| `engine.py` | `evaluate_offer` wiring + `Result` shape (provided) | all of the above |

Each unit has one purpose and a narrow interface, testable in isolation.

## 6. Testing strategy

- Make the four provided `tests/test_cases.py` expectations pass.
- **Brute-force oracle**: on small cases, enumerate *all* valid integer creditor
  vectors and confirm the greedy solver's chosen schedule matches the optimum for
  the front-loading objective — this proves the lexmin interpretation is optimal.
- **Linear-scan oracle** for minima: step by 1 cent and confirm it agrees with the
  binary search.
- Property/edge tests: exact-sum, non-decreasing, floors, token cap, tier floor,
  `max_segments` cap, same-day credits-before-debits, a balance that hits exactly
  `$0`, the horizon limit, no fee before the first payment date, fee fully
  collected by horizon, default (omitted) `first_payment_date`, EOM cadence.

## 7. Experiments / profiling (deliverable)

- Per-algorithm wall-clock timing on the 4 cases + synthetic cases.
- `cProfile` hotspot breakdown.
- Scaling study: vary `k` / horizon length and measure solver time; binary search
  vs linear scan for minima.
- Greedy-vs-oracle correctness cross-check table.
- Results written into the README with tables.

## 8. Assumptions (also surfaced in README)

1. The offer balance field is read as `current_balance_cents` (matches the
   scaffolding, loaders, JSON, and smoke tests); the loader *also* accepts
   `creditor_balance_cents` for forward-compatibility with the §3 note.
2. Lump sum is placed on `first_draft_date` (earliest modifiable date; earlier is
   weakly more useful per the spec).
3. When ballooning is allowed we always emit a balloon (it dominates for the
   objective), so `pay_shape_used == "balloon"`.
4. "Monthly increment" applies to **every** draft dated after `as_of`; `N` counts
   all of them even if late ones arrive too late to help.
