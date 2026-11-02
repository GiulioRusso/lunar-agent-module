"""Capabilities, backend isolation and physically coupled cross-range control."""

from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from typing import Any

import pytest
from test_agent_interface import _obs
from test_loop_throttle import FakeClient, FakeClock

from luminary_agent.plant.dynamics import Control, PlanarState, derivative
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.surface import MOON_RATE_RAD_S, horizontal_speed_relative_to_surface
from luminary_agent.policies.actions import ActionAvailability
from luminary_agent.policies.base import (
    Intent,
    abort,
    adjust_rod,
    command,
    dsky_key,
    redesignate,
    return_auto,
    select_p66,
    take_manual,
    validate_intent,
)
from luminary_agent.safety.monitor import SafetyMonitor
from luminary_agent.sim.executor import Executor
from luminary_agent.sim.frames import IDENTITY, PLANE_IS_XY
from luminary_agent.sim.loop import PipaAxes, Simulation
from luminary_agent.sim.manual_control import MAX_TILT_RAD, ManualController
from luminary_agent.sim.operations import OperationContext, OperationResult


class Client(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []
        self.writes: list[object] = []

    async def press_key(self, key: str) -> None:
        self.keys.append(key)

    async def write_channels(self, words: object) -> None:
        self.writes.append(words)


def setup() -> tuple[Executor, Client, Simulation]:
    client = Client()
    state = PlanarState(150, 0, -2, MOON_RATE_RAD_S * (R_MOON + 150), 7800)
    sim = Simulation(
        client,  # type: ignore[arg-type]
        FakeClock(),
        state,
        PipaAxes(0o37, 0o40, 0o41),
        PLANE_IS_XY,
        IDENTITY,
        dry_mass_kg=6800,
    )
    return Executor(sim, client), client, sim  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "intent", [return_auto(5), select_p66(5), adjust_rod(5, 2), redesignate(5, 20, -10), abort(5)]
)
def test_known_but_unimplemented_procedures_do_not_mutate_flight(intent: Intent) -> None:
    ex, client, sim = setup()
    validate_intent(intent, 0)
    before = sim.state
    result = asyncio.run(ex.execute(intent))
    assert result.status == "unsupported" and result.message
    assert sim.state == before and sim.manual is None
    assert not client.keys and not client.writes
    assert not ex.availability(intent.kind).supported


@pytest.mark.parametrize(
    "kind,params",
    [
        ("command", {"cross_ms": float("nan")}),
        ("adjust_rod", {"clicks": 1.5}),
        ("adjust_rod", {"clicks": True}),
        ("adjust_rod", {"clicks": 11}),
        ("abort", {"stage": "both"}),
        ("redesignate", {"downrange_m": 1}),
        ("redesignate", {"downrange_m": 1001, "cross_m": 0}),
        ("dsky_key", {"key": "PRO"}),
        ("dsky_key", {"key": ["VERB", "1"]}),
    ],
)
def test_action_schemas_reject_invalid_inputs(kind: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_intent(Intent(kind, params, 5), 0)


def test_manual_command_exposes_clamped_three_axis_targets() -> None:
    ex, _, _ = setup()
    assert not ex.availability("command").available
    asyncio.run(ex.apply(take_manual(5)))
    result = asyncio.run(ex.execute(command(5, -10, 7, -8)))
    assert result.status == "applied"
    assert dict(result.effective_params) == {
        "descent_rate_ms": -6,
        "horizontal_ms": 5,
        "cross_ms": -5,
    }
    assert ex.policy_targets == (-6, 5, -5)
    assert ex.availability("command").available


def test_key_delivery_is_submitted_rate_limited_and_does_not_advance_physics() -> None:
    ex, client, sim = setup()
    result = asyncio.run(ex.execute(dsky_key(5, "VERB")))
    assert result.status == "submitted" and client.keys == ["VERB"]
    assert sim.clock.sim_time_s == 0
    assert not ex.availability("dsky_key").available
    assert asyncio.run(ex.execute(dsky_key(5, "1"))).status == "rejected"
    asyncio.run(sim.run(0.14))
    assert asyncio.run(ex.execute(dsky_key(5, "1"))).status == "submitted"
    assert client.keys == ["VERB", "1"]


def test_safety_authority_also_blocks_backend_actions() -> None:
    ex, client, _ = setup()
    ex.safety_active = True
    assert asyncio.run(ex.execute(dsky_key(5, "ENTR"))).status == "rejected"
    assert not client.keys
    assert asyncio.run(ex.execute(take_manual(5), safety=True)).status == "applied"
    assert asyncio.run(ex.execute(command(5, -1, 0, 0), safety=True)).status == "applied"


def test_procedure_backend_can_be_added_without_changing_policy_or_executor() -> None:
    ex, _, sim = setup()
    asyncio.run(ex.execute(take_manual(5)))

    class VerifiedTestBackend:
        def availability(self, action: str, context: OperationContext) -> ActionAvailability:
            return ActionAvailability(action, action == "return_auto", context.mode == "manual")

        async def execute(self, intent: Intent, context: OperationContext) -> OperationResult:
            assert context.mode == "manual" and intent.kind == "return_auto"
            # Test double only: a real backend must verify AGC mode and synchronize the actuator.
            sim.manual = None
            return OperationResult("applied", "verified test handover")

    ex.operations = VerifiedTestBackend()
    result = asyncio.run(ex.execute(return_auto(5)))
    assert (
        result.status == "applied"
        and result.mode_before == "manual"
        and result.mode_after == "auto"
    )


def test_backend_failure_is_reported_without_retrying() -> None:
    ex, client, _ = setup()

    async def fail(key: str) -> None:
        client.keys.append(key)
        raise OSError("lost connection after write")

    client.press_key = fail  # type: ignore[method-assign]
    result = asyncio.run(ex.execute(dsky_key(5, "VERB")))
    assert result.status == "failed" and client.keys == ["VERB"]


def test_cross_range_steering_shares_thrust_and_tilt_budget() -> None:
    state = PlanarState(100, 0, -2, 20, 7800)
    pilot = ManualController()
    pilot.set_targets(-1, -5, 5)
    control = pilot.control_3d(state, 0, -20)
    engine = DescentEngine()
    thrust, mdot = engine.thrust_and_mdot(control.throttle)
    d = derivative(state, control, engine)
    r = R_MOON + state.h_m
    ar = d.hdot_ms - state.xdot_ms**2 / r + MU_MOON / r**2
    at = d.xdot_ms + state.hdot_ms * state.xdot_ms / r
    az = thrust * control.normal_fraction / state.mass_kg
    assert math.hypot(ar, at, az) == pytest.approx(thrust / state.mass_kg)
    assert math.atan2(math.hypot(at, az), ar) <= MAX_TILT_RAD + 1e-10
    assert d.mass_kg == -mdot and az > 0


def test_cross_range_target_changes_trajectory_and_default_controller_arrests_drift() -> None:
    async def fly(target: float) -> Simulation:
        ex, _, sim = setup()
        sim.zdot_ms = 3
        await ex.execute(take_manual(5))
        await ex.execute(command(5, -1, 0, target))
        await sim.run(20)
        return sim

    stopped = asyncio.run(fly(0))
    steered = asyncio.run(fly(-2))
    assert abs(stopped.zdot_ms) < 0.05
    assert steered.zdot_ms == pytest.approx(-2, abs=0.05)
    assert steered.z_m < stopped.z_m - 20
    assert abs(horizontal_speed_relative_to_surface(stopped.state)) < 0.05


def test_cross_range_only_excess_speed_triggers_safety() -> None:
    obs = replace(_obs(mode="manual", alt=10), horizontal_ms=0, cross_velocity_ms=4)
    veto = SafetyMonitor().check(obs)
    assert veto is not None and veto.intent.params["cross_ms"] == 0


@pytest.mark.parametrize("normal", [float("nan"), float("inf"), -1.1, 1.1])
def test_impossible_thrust_vectors_are_rejected(normal: float) -> None:
    with pytest.raises(ValueError):
        Control(0.5, 0, normal)


def test_observation_and_inspector_expose_capabilities_and_structured_feedback() -> None:
    from dataclasses import asdict

    from viz_records import decision, tick

    from luminary_agent.viz.view_model import FrameBuilder

    ex, _, _ = setup()
    result = asyncio.run(ex.execute(abort(5)))
    obs = replace(
        _obs(),
        action_capabilities=ex.capabilities,
        previous_action_result=result,
        cross_velocity_ms=2.5,
    )
    text = obs.to_text()
    assert "dsky_key" in text and "abort requires" in text and "cross_v=+2.50" in text
    record = decision("abort")
    record.update(obs=obs.to_dict(), execution=asdict(result), applied=result.to_text())
    builder = FrameBuilder(0, 6800)
    builder.decision(record)
    frame = builder.tick(tick(zdot_ms=2.5))
    assert frame.cross_velocity_ms == 2.5
    assert "dsky_key" in frame.available_actions and "abort" not in frame.available_actions
    assert frame.action_status == "unsupported"


def test_valid_unsupported_request_is_feedback_not_a_policy_failure() -> None:
    from luminary_agent.policies.runner import DecisionRunner
    from luminary_agent.sim.descent import _consult
    from luminary_agent.sim.observation import Observation

    class AbortPolicy:
        name = "abort-test"

        def reset(self) -> None:
            pass

        def decide(self, obs: Observation, t_s: float) -> Intent:
            return abort(t_s + 1)

    ex, _, sim = setup()
    runner = DecisionRunner(AbortPolicy())
    asyncio.run(_consult(runner, ex, sim, _obs(), "test", []))
    assert runner.failures == 0 and not runner.disabled
    assert ex.last_feedback is not None and ex.last_feedback.status == "unsupported"
