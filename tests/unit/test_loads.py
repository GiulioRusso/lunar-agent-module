"""Unit tests for agc/loads.py:plan_loads, which groups {address: word} into P27 V71 blocks and
V72 scatter batches. `_covered` flattens a plan back to {address: word} to check nothing is
lost or duplicated.

Run alone: `uv run pytest tests/unit/test_loads.py -v`.
"""

from luminary_agent.agc.loads import MIN_RUN, LoadPlan, plan_loads
from luminary_agent.agc.uplink import MAX_V71_WORDS, MAX_V72_PAIRS


def _covered(plan: LoadPlan) -> dict[int, int]:
    out: dict[int, int] = {}
    for start, block in plan.blocks:
        for i, w in enumerate(block):
            out[start + i] = w
    for batch in plan.scatters:
        out.update(dict(batch))
    return out


def test_consecutive_words_become_one_v71_block() -> None:
    words = {0o1400 + i: i + 1 for i in range(6)}
    plan = plan_loads(words)
    assert plan.blocks == ((0o1400, (1, 2, 3, 4, 5, 6)),)
    assert plan.scatters == ()


def test_short_runs_and_singletons_are_batched_into_v72() -> None:
    words = {0o100: 1, 0o102: 2, 0o200: 3, 0o201: 4}  # nothing reaches MIN_RUN
    plan = plan_loads(words)
    assert plan.blocks == ()
    assert plan.sessions == 1
    assert dict(plan.scatters[0]) == words


def test_long_run_is_split_at_the_p27_word_limit() -> None:
    n = MAX_V71_WORDS * 2 + MIN_RUN
    words = {0o1400 + i: i for i in range(n)}
    plan = plan_loads(words)
    assert [len(b) for _, b in plan.blocks] == [MAX_V71_WORDS, MAX_V71_WORDS, MIN_RUN]
    assert _covered(plan) == words


def test_a_run_never_crosses_a_bank_boundary() -> None:
    words = {0o1777 + i: i for i in range(0, 1)} | {0o2000 + i: i for i in range(4)}
    plan = plan_loads(words | {0o1776: 9, 0o1775: 8})
    for start, block in plan.blocks:
        assert (start % 0o400) + len(block) <= 0o400
    assert _covered(plan) == words | {0o1776: 9, 0o1775: 8}


def test_short_tail_of_a_long_run_falls_back_to_v72() -> None:
    words = {0o1400 + i: i for i in range(MAX_V71_WORDS + 1)}  # 18 + 1 tail word
    plan = plan_loads(words)
    assert len(plan.blocks) == 1 and len(plan.scatters) == 1
    assert _covered(plan) == words


def test_v72_batches_respect_the_pair_limit() -> None:
    words = {0o100 + 3 * i: i for i in range(MAX_V72_PAIRS * 2 + 1)}  # all isolated
    plan = plan_loads(words)
    assert [len(b) for b in plan.scatters] == [MAX_V72_PAIRS, MAX_V72_PAIRS, 1]


def test_every_word_is_loaded_exactly_once() -> None:
    words = {0o1400 + i: i for i in range(40)} | {0o50: 1, 0o60: 2, 0o2200: 3}
    plan = plan_loads(words)
    assert _covered(plan) == words
    sent = sum(len(b) for _, b in plan.blocks) + sum(len(s) for s in plan.scatters)
    assert sent == len(words)
