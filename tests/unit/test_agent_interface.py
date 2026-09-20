import asyncio
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.policies.base import command, hold, take_manual
from luminary_agent.policies.scripted import NullAgent, ScriptedAgent
from luminary_agent.sim.executor import Executor
from luminary_agent.sim.manual_control import ManualController
from luminary_agent.sim.observation import Observation


def _obs(mode: str = "auto", alt: float = 500.0, program: int | None = 64) -> Observation:
    return Observation(100.0, mode, program, 6, 64, 1, 2, 3, (0o1410,), alt, -2.0, 0.5, 9000.0,
                       7500.0, 700.0)  # fmt: skip


class _Client:
    def __init__(self) -> None:
        self.writes: list[Mapping[int, int]] = []

    async def write_channels(self, words: Mapping[int, int]) -> None:
        self.writes.append(words)


def _executor() -> tuple[Executor, _Client, Any]:
    sim = SimpleNamespace(manual=None)
    client = _Client()
    return Executor(sim, client), client, sim  # type: ignore[arg-type]


def test_observation_text_and_dict() -> None:
    o = _obs()
    assert "alarms=1410" in o.to_text() and "alt=500.0m" in o.to_text()
    assert o.to_dict()["altitude_m"] == 500.0


def test_null_and_scripted_decisions() -> None:
    assert NullAgent().decide(_obs(alt=10.0), 5.0).kind == "hold"
    s = ScriptedAgent(takeover_h_m=150.0)
    assert s.decide(_obs(alt=500.0), 5.0).kind == "hold"
    assert s.decide(_obs(alt=100.0), 5.0).kind == "take_manual"
    assert s.decide(_obs(alt=500.0, program=65), 5.0).kind == "take_manual"
    assert s.decide(_obs(mode="manual", alt=10.0), 5.0).kind == "hold"


def test_executor_takeover_then_command() -> None:
    ex, client, sim = _executor()
    assert asyncio.run(ex.apply(command(1.0, -1.0))).startswith("rejected")
    assert asyncio.run(ex.apply(take_manual(1.0))).startswith("ok")
    assert sim.manual is not None and len(client.writes) == 1 and ex.mode == "manual"
    assert asyncio.run(ex.apply(take_manual(2.0))).startswith("ignored")
    assert asyncio.run(ex.apply(command(1.0, descent_rate_ms=-1.5, horizontal_ms=0.5))) == "ok"
    assert ex.controller.descent_rate_ms == -1.5 and ex.controller.horizontal_ms == 0.5
    assert asyncio.run(ex.apply(hold(1.0))) == "ok"
    assert asyncio.run(ex.apply(SimpleNamespace(kind="dance", params={}))).startswith("rejected")  # type: ignore[arg-type]


def test_targets_are_clamped_and_reported() -> None:
    c = ManualController()
    note = c.set_targets(-30.0, 50.0)
    assert c.descent_rate_ms == -6.0 and c.horizontal_ms == 5.0 and "clamped" in note


def test_commanded_descent_rate_changes_throttle() -> None:
    s = PlanarState(100.0, 0.0, -1.0, 100.0, 7500.0)
    fast, slow = ManualController(), ManualController()
    fast.set_targets(-4.0, 0.0)
    slow.set_targets(-0.5, 0.0)
    assert slow.control(s)[0] > fast.control(s)[0]
