"""Unit tests for sim/p63_crew.py:wait_for_display with a scripted fake AGC: every `step`
advances a FakeDsky to the next (verb, noun) in its script, so no emulator is needed.

Run alone: `uv run pytest tests/unit/test_p63_crew.py -v`.
"""

import asyncio
from typing import Any

import pytest

from luminary_agent.sim.p63_crew import CrewProcedureError, wait_for_display


class FakeDsky:
    def __init__(self, script: list[tuple[int | None, int | None]]) -> None:
        self._script = script
        self.verb_number: int | None = None
        self.noun_number: int | None = None
        self.r1 = self.r2 = self.r3 = None

    def advance(self) -> None:
        if self._script:
            self.verb_number, self.noun_number = self._script.pop(0)


class FakeClient:
    def __init__(self, script: list[tuple[int | None, int | None]]) -> None:
        self.dsky = FakeDsky(script)


class FakeAgc:
    def __init__(self, client: FakeClient) -> None:
        self._client = client
        self.steps = 0

    async def step(self, n: int) -> str:
        self.steps += 1
        self._client.dsky.advance()
        return ""


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_waits_until_the_display_matches() -> None:
    client = FakeClient([(None, None), (6, 18), (50, 18)])
    agc = FakeAgc(client)
    run(wait_for_display(agc, client, 50, 18))  # type: ignore[arg-type]
    assert agc.steps == 3


def test_seen_verb_must_appear_first() -> None:
    """V50 N18 appears twice (prompt, then 'maneuver finished'); the second is only real after
    the static V06 N18 has been seen, so an early V50 N18 must not satisfy the wait.
    """
    client = FakeClient([(50, 18), (50, 18), (6, 18), (50, 18)])
    agc = FakeAgc(client)
    run(wait_for_display(agc, client, 50, 18, seen_verb=6))  # type: ignore[arg-type]
    assert agc.steps == 4


def test_timeout_reports_what_was_actually_on_the_display() -> None:
    client = FakeClient([(6, 61)] * 5)
    with pytest.raises(CrewProcedureError, match=r"V50 N25.*V6 N61"):
        run(wait_for_display(FakeAgc(client), client, 50, 25, max_chunks=5))  # type: ignore[arg-type]
