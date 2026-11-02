"""Unit tests for the agent interface: Observation (sim/observation.py), the baseline policies
(policies/scripted.py), the Executor (sim/executor.py) and the ManualController.
The Executor is tested against fakes: `SimpleNamespace(manual=None)` stands in for a Simulation
and `_Client` records channel writes instead of sending them to a real AGC.

Run alone: `uv run pytest tests/unit/test_agent_interface.py -v`.
"""

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


# A fixed Observation (positional fields, in the dataclass order) with a few knobs to vary.
def _obs(mode: str = "auto", alt: float | None = 500.0, program: int | None = 64) -> Observation:
    return Observation(
        100.0,
        mode,
        program,
        6,
        64,
        1,
        2,
        3,
        (0o1410,),
        alt,
        520.0,
        -2.0,
        0.5,
        9000.0,
        7500.0,
        700.0,
    )


class _Client:
    """Fake AgcClient: remembers what would have been written to the AGC."""

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
    assert "alarms=1410" in o.to_text() and "radar_alt=500m agc_alt=520m" in o.to_text()
    assert o.to_dict()["radar_altitude_m"] == 500.0


def test_null_and_scripted_decisions() -> None:
    assert NullAgent().decide(_obs(alt=10.0), 5.0).kind == "hold"
    s = ScriptedAgent(takeover_h_m=150.0)
    assert s.decide(_obs(alt=500.0), 5.0).kind == "hold"
    assert s.decide(_obs(alt=100.0), 5.0).kind == "take_manual"
    assert s.decide(_obs(alt=500.0, program=65), 5.0).kind == "take_manual"
    assert s.decide(_obs(mode="manual", alt=10.0), 5.0).kind == "hold"
    assert s.decide(_obs(alt=None), 5.0).kind == "hold"  # no radar lock: no altitude trigger


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


def test_surface_is_seen_only_when_low_enough_to_see_it() -> None:
    from luminary_agent.plant.terrain import Bump, Hazard, Surface
    from luminary_agent.sim.observation import surface_view

    s = Surface(
        0,
        hazards=(Hazard("crater", 100.0, 0.0, 20.0), Hazard("boulder", 900.0, 0.0, 2.0)),
        bumps=(Bump(0.0, 60.0, 40.0, 60.0),),
    )
    assert surface_view(None, 0.0, 0.0, 100.0) == {}  # no surface scored
    assert surface_view(s, -50.0, 5.0, 5_000.0) == {}  # too high to see the ground
    mid = surface_view(s, -50.0, 5.0, 1_500.0)
    assert mid == {"target_downrange_m": -50.0, "target_cross_m": 5.0}  # only the target
    low = surface_view(s, -50.0, 5.0, 200.0)
    assert low["slope_here_deg"] == s.slope_deg(-50.0, 5.0)
    assert low["hazards_near"] == (
        ("crater", 150.0, -5.0, 20.0),
    )  # the far boulder is out of range


def test_the_observation_text_names_the_target_and_terrain() -> None:
    from luminary_agent.sim.observation import Observation

    o = Observation(
        10.0, "auto", 64, 6, 64, 1, 2, 3, (), 100.0, 110.0, -2.0, 0.5, 1000.0, 7000.0, 200.0,
        target_downrange_m=-40.0, target_cross_m=12.0, slope_here_deg=2.5,
        hazards_near=(("boulder", 30.0, -4.0, 2.0),),
    )  # fmt: skip
    text = o.to_text()
    assert "target: -40m downrange, +12m cross" in text
    assert "slope 2.5deg" in text and "boulder r=2m at (+30,-4)" in text
    assert (
        "target"
        not in Observation(
            10.0, "auto", 64, 6, 64, 1, 2, 3, (), None, None, 0.0, 0.0, 0.0, 7000.0, 0.0
        ).to_text()
    )
