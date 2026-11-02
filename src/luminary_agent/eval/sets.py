"""Frozen evaluation sets (CODE_REVIEW.md Phase 3).

FROZEN: 3 tiers x 20 seeds = 60 episodes, the only numbers that may be reported. Never tune on it,
never re-draw it (a change to dispersions.py that alters `sample(seed, tier)` invalidates every
result obtained on it). DEV: 3 tiers x 5 other seeds = 15 episodes, free to tune against.

Each set is a tuple of (tier, seed) pairs, e.g. DEV = ((1,0), (1,1), ..., (3,4)).
Used by `luminary eval --set dev|frozen` and `make eval` / `make frozen`.
"""

from __future__ import annotations

TIERS = (1, 2, 3)
FROZEN: tuple[tuple[int, int], ...] = tuple((t, s) for t in TIERS for s in range(100, 120))
DEV: tuple[tuple[int, int], ...] = tuple((t, s) for t in TIERS for s in range(0, 5))
SETS = {"frozen": FROZEN, "dev": DEV}
