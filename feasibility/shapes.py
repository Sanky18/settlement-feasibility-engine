"""Creditor-payment *shape* constructors — the open-ended crux of the assignment.

The single economic objective is "collect the program fee as early as possible".
Section 2 of the design doc shows this is equivalent to keeping cumulative creditor
outflow **as low as possible early**, i.e. **lexicographically minimizing**
``(p_1, ..., p_k)`` subject to the hard constraints. Each shape below is that
lexmin under its creditor flag:

  * ``even``      — all payments equal (remainder cents pushed onto the latest).
  * ``balloon``   — floors early, final payment absorbs the remainder.
  * ``staircase`` — lexmin with at most ``max_segments`` distinct levels.

Everything is integer cents.
"""

from __future__ import annotations

from itertools import combinations

from feasibility.models import CreditorRules


def floor_vector(k: int, rules: CreditorRules) -> list[int]:
    """The minimal non-decreasing floor for each of ``k`` positions (1-based).

    The floor at position ``i`` is the maximum of:
      * base ``min_payment_cents`` for the first ``max_token_pays`` positions, and
        ``min_payment_cents + 1`` afterwards (the token-pay rule: only that many
        payments may *equal* the base minimum; further ones must strictly exceed it);
      * any ``min_payment_tiers`` step-up that applies from that position onward.
    A running max then enforces the non-decreasing requirement.
    """
    base = rules.min_payment_cents
    floors: list[int] = []
    running = 0
    for i in range(1, k + 1):
        token_floor = base if i <= rules.max_token_pays else base + 1
        tier_floor = base
        for frm, min_cents in rules.min_payment_tiers:
            if i >= frm:
                tier_floor = max(tier_floor, min_cents)
        f = max(token_floor, tier_floor, running)
        floors.append(f)
        running = f
    return floors


def _distribute_remainder(total: int, n: int) -> list[int]:
    """Split ``total`` into ``n`` near-equal integers, larger ones LAST.

    e.g. _distribute_remainder(50000, 6) -> [8333, 8333, 8333, 8333, 8334, 8334].
    Keeps the sequence non-decreasing (the "as equal as possible" rule, §5.7).
    """
    base, rem = divmod(total, n)
    return [base] * (n - rem) + [base + 1] * rem


def build_even(k: int, rules: CreditorRules, offer_total: int) -> list[int] | None:
    """All ``k`` payments equal (remainder onto the latest)."""
    if k <= 0 or offer_total < 0:
        return None
    vec = _distribute_remainder(offer_total, k)
    return vec if _respects_floors(vec, rules) else None


def build_balloon(k: int, rules: CreditorRules, offer_total: int) -> list[int] | None:
    """Floors for payments ``1..k-1``; the final payment absorbs the remainder."""
    if k <= 0:
        return None
    floors = floor_vector(k, rules)
    if k == 1:
        vec = [offer_total]
        return vec if offer_total >= floors[0] else None
    head = floors[:-1]
    balloon = offer_total - sum(head)
    # Non-decreasing + the balloon's own floor.
    if balloon < max(head[-1], floors[-1]):
        return None
    return head + [balloon]


def build_staircase(k: int, rules: CreditorRules, offer_total: int) -> list[int] | None:
    """Lexmin non-decreasing vector using at most ``max_segments`` distinct levels.

    A "level/segment" is a contiguous block of (near-)equal payments. We enumerate
    every way to split the ``k`` positions into ``t <= max_segments`` consecutive
    blocks, hold the earlier blocks at their floor, and dump all remaining cents
    into the *last* block (split as-equal-as-possible, mirroring the even-pays
    remainder rule, §5.7). Among all valid layouts we keep the lexicographically
    smallest payment vector — which is exactly the front-loading objective.
    """
    if k <= 0:
        return None
    floors = floor_vector(k, rules)
    s = max(1, min(rules.max_segments, k))
    best: list[int] | None = None

    for t in range(1, s + 1):
        # Choose t-1 breakpoints among the k-1 internal gaps -> t consecutive blocks.
        for cuts in combinations(range(1, k), t - 1):
            bounds = [0, *cuts, k]
            vec = _build_layout(bounds, floors, offer_total)
            if vec is not None and (best is None or vec < best):
                best = vec
    return best


def _build_layout(bounds: list[int], floors: list[int], offer_total: int) -> list[int] | None:
    """Build one staircase layout: blocks at floor, last block absorbs the rest."""
    blocks = [(bounds[j], bounds[j + 1]) for j in range(len(bounds) - 1)]
    vec = list(floors)  # baseline: every payment at its floor (lexmin start)
    # Each block is held constant at the max floor within it (>= previous block).
    prev_level = 0
    for lo, hi in blocks:
        level = max(prev_level, max(floors[lo:hi]))
        for i in range(lo, hi):
            vec[i] = level
        prev_level = level
    baseline = sum(vec)
    extra = offer_total - baseline
    if extra < 0:
        return None
    if extra == 0:
        return vec
    # Dump all extra into the LAST block, as-equal-as-possible (larger ones last).
    lo, hi = blocks[-1]
    n = hi - lo
    raised = _distribute_remainder(vec[lo] * n + extra, n)
    # The raised last block must stay >= the preceding block.
    if blocks[:-1] and raised[0] < vec[blocks[-2][1] - 1]:
        return None
    vec[lo:hi] = raised
    return vec


def _respects_floors(vec: list[int], rules: CreditorRules) -> bool:
    """Validate floors, the token-pay cap, tiers, and non-decreasing for ``vec``."""
    floors = floor_vector(len(vec), rules)
    if any(p < f for p, f in zip(vec, floors)):
        return False
    if any(b < a for a, b in zip(vec, vec[1:])):
        return False
    token_pays = sum(1 for p in vec if p == rules.min_payment_cents)
    return token_pays <= rules.max_token_pays
