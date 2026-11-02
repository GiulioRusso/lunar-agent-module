"""Unit tests for agc/uplink.py input validation: bad P27 loads are rejected *before* any key is
pressed, so these need no emulator (`FakeAgc` only has to look like a stepped process).

Run alone: `uv run pytest tests/unit/test_uplink_validation.py -v`.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.uplink import MAX_V71_WORDS, MAX_V72_PAIRS, UpdateError, Updater


def _updater() -> Updater:
    class FakeAgc:
        mode = "stepped"

    return Updater(FakeAgc(), object())  # type: ignore[arg-type]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_limits_come_from_p27_not_from_hope() -> None:
    assert MAX_V71_WORDS == 18  # II <= 20 decimal, II = words + 2
    assert MAX_V72_PAIRS == 9  # II <= 19, II = 2*pairs + 1


def test_realtime_process_is_rejected() -> None:
    proc = AgcProcess(Path("."), mode="realtime")
    with pytest.raises(UpdateError, match="stepped"):
        Updater(proc, object())  # type: ignore[arg-type]


@pytest.mark.parametrize("words", [[], [0] * 19])
def test_v71_word_count_bounds(words: list[int]) -> None:
    with pytest.raises(UpdateError, match="words per load"):
        run(_updater().v71(0o55, words))


def test_v71_rejects_block_running_off_its_bank() -> None:
    with pytest.raises(UpdateError, match="bank"):
        run(_updater().v71(0o1777, [1, 2]))  # last word of bank 3 + one more


def test_v71_rejects_words_that_are_not_15_bit() -> None:
    with pytest.raises(UpdateError, match="15-bit"):
        run(_updater().v71(0o55, [0o100000]))


def test_v72_pair_count_bounds() -> None:
    with pytest.raises(UpdateError, match="pairs per load"):
        run(_updater().v72([(0o55, 0)] * 10))


def test_ecadr_out_of_range() -> None:
    with pytest.raises(UpdateError, match="ECADR"):
        run(_updater().v72([(0o4000, 0)]))
