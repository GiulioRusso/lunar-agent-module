"""Unit tests for sim/loop.py:Simulation's throttle and thrust-direction handling, with fakes
instead of a real AGC: FakeClient (records PIPA pulses, exposes an ActuatorState the test flips
engine_on on), FakeClock (just adds dt), and a guidance reader that plays back a scripted list
of GuidanceSamples. That isolates the loop's logic from the emulator entirely.

Run alone: `uv run pytest tests/unit/test_loop_throttle.py -v`.
"""

import asyncio
import math
from typing import Any

import pytest

from luminary_agent.agc.actuators import ActuatorState
from luminary_agent.agc.guidance import GuidanceSample
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import F_MAX_N
from luminary_agent.plant.throttle import MIN_COUNTS, ThrottleActuator
from luminary_agent.sim.frames import IDENTITY, PLANE_IS_XY
from luminary_agent.sim.loop import PipaAxes, Simulation


class FakeDsky:
    """A blank display (every field None)."""

    program_number = verb_number = noun_number = r1 = r2 = r3 = None


class FakeClient:
    """Stands in for AgcClient: engine state is set by the test, pulses are recorded."""

    def __init__(self) -> None:
        self.actuators = ActuatorState()
        self.dsky = FakeDsky()
        self.pulses: list[tuple[int, int]] = []

    async def send_pipa_pulses(self, register: int, count: int) -> None:
        self.pulses.append((register, count))


class FakeClock:
    """Stands in for SteppedClock: no AGC to step, time just advances."""

    def __init__(self) -> None:
        self.sim_time_s = 0.0

    async def advance(self, dt_s: float) -> None:
        self.sim_time_s += dt_s


def _sim(
    client: FakeClient, script: list[GuidanceSample], every: int = 5
) -> tuple[Simulation, list[int]]:
    """A simulation whose guidance reader plays back `script` (repeating the last sample)."""
    reads: list[int] = []

    async def reader() -> GuidanceSample:
        reads.append(1)
        return script[min(len(reads) - 1, len(script) - 1)]

    sim = Simulation(
        client,  # type: ignore[arg-type]
        FakeClock(),
        PlanarState(15_000.0, 0.0, 0.0, 1_680.0, 15_000.0),
        PipaAxes(x=0o37, y=0o40, z=0o41),
        PLANE_IS_XY,
        IDENTITY,
        actuator=ThrottleActuator(),
        read_guidance_sample=reader,
        guidance_every_ticks=every,
    )
    return sim, reads


def run(coro: Any) -> Any:
    """Run a coroutine to completion from synchronous test code."""
    return asyncio.run(coro)


def _ticks(sim: Simulation, n: int) -> list[float]:
    """Tick `n` times; return the thrust of each tick."""

    async def go() -> list[float]:
        return [(await sim.tick())["thrust_n"] for _ in range(n)]

    return run(go())  # type: ignore[no-any-return]


def test_no_thrust_and_no_guidance_reads_until_the_agc_lights_the_engine() -> None:
    client = FakeClient()
    sim, reads = _sim(client, [GuidanceSample(0, None, 7)])
    assert _ticks(sim, 10) == [0.0] * 10
    assert reads == []


def test_engine_on_starts_at_minimum_throttle_and_burns_propellant() -> None:
    client = FakeClient()
    sim, _ = _sim(client, [GuidanceSample(0, None, 7)])
    client.actuators.engine_on = True
    (thrust,) = _ticks(sim, 1)
    assert math.isclose(thrust, 0.10 * F_MAX_N)
    assert sim.state.mass_kg < 15_000.0


def test_guidance_is_sampled_on_a_cadence_not_every_tick() -> None:
    client = FakeClient()
    sim, reads = _sim(client, [GuidanceSample(0, None, 7)], every=5)
    client.actuators.engine_on = True
    _ticks(sim, 20)
    # once at ignition, then at ticks 5, 10, 15 (tick 0 is the ignition read itself)
    assert len(reads) == 4


def test_a_new_command_stamp_applies_the_increment_once() -> None:
    client = FakeClient()
    sim, _ = _sim(
        client,
        [
            GuidanceSample(0, None, 7),  # ignition: stamp 7 recorded, nothing applied
            GuidanceSample(500, None, 7),  # same stamp -> same command, not re-applied
            GuidanceSample(500, None, 9),  # new stamp -> apply +500 once
            GuidanceSample(500, None, 9),  # ...and not again
        ],
        every=2,
    )
    client.actuators.engine_on = True
    _ticks(sim, 9)
    assert sim.actuator is not None
    total_applied = (sim.actuator.counts - MIN_COUNTS) + sim.actuator.pending
    assert total_applied == pytest.approx(500.0)


def test_commands_after_the_first_are_not_missed() -> None:
    """The regression that motivated stamps: a strobe *edge* counter saw only the first
    command(s) because CHAN14 bit 4 is latched on. Every stamp change must be applied.
    """
    client = FakeClient()
    sim, _ = _sim(
        client,
        [
            GuidanceSample(0, None, 1),
            GuidanceSample(300, None, 2),
            GuidanceSample(-100, None, 3),
            GuidanceSample(50, None, 4),
        ],
        every=2,
    )
    client.actuators.engine_on = True
    _ticks(sim, 9)
    assert sim.actuator is not None
    assert (sim.actuator.counts - MIN_COUNTS) + sim.actuator.pending == pytest.approx(250.0)


def test_a_stale_pre_ignition_command_is_not_applied() -> None:
    client = FakeClient()
    sim, _ = _sim(client, [GuidanceSample(-4096, None, 5)], every=2)  # pre-ignition FLATOUT-down
    client.actuators.engine_on = True
    _ticks(sim, 9)
    assert sim.actuator is not None
    assert sim.actuator.counts == pytest.approx(MIN_COUNTS)  # not driven anywhere by a stale value


def test_engine_off_again_cuts_thrust() -> None:
    client = FakeClient()
    sim, _ = _sim(client, [GuidanceSample(0, None, 1)])
    client.actuators.engine_on = True
    _ticks(sim, 1)
    client.actuators.engine_on = False
    assert _ticks(sim, 1) == [0.0]


def test_relighting_forgets_the_previous_burns_stamp() -> None:
    client = FakeClient()
    sim, _ = _sim(client, [GuidanceSample(0, None, 1), GuidanceSample(200, None, 1)], every=3)
    client.actuators.engine_on = True
    _ticks(sim, 4)
    client.actuators.engine_on = False
    _ticks(sim, 1)
    client.actuators.engine_on = True
    _ticks(sim, 1)
    assert sim._stamp_seen is not None


def test_actuator_without_a_reader_is_rejected() -> None:
    with pytest.raises(ValueError, match="read_guidance_sample"):
        Simulation(
            FakeClient(),  # type: ignore[arg-type]
            FakeClock(),
            PlanarState(1.0, 0.0, 0.0, 0.0, 1.0),
            PipaAxes(0o37, 0o40, 0o41),
            PLANE_IS_XY,
            IDENTITY,
            actuator=ThrottleActuator(),
        )


def _direction_sim(theta_x: float = 0.0) -> Simulation:
    """A Simulation placed at angle theta_x around the Moon, for _apply_direction tests."""
    client = FakeClient()
    return Simulation(
        client,  # type: ignore[arg-type]
        FakeClock(),
        PlanarState(15_000.0, theta_x * 1_738_090.0, 0.0, 1_680.0, 15_000.0),
        PipaAxes(x=0o37, y=0o40, z=0o41),
        PLANE_IS_XY,
        IDENTITY,
    )


def test_thrust_along_local_up_is_zero_pitch() -> None:
    sim = _direction_sim()
    sim._apply_direction((1.0, 0.0, 0.0))  # +X_sm = +e1 = up at theta 0
    assert sim.pitch_rad == pytest.approx(0.0, abs=1e-12)


def test_thrust_opposing_travel_is_positive_pitch_of_90_degrees() -> None:
    """A retro burn: thrust points against the direction of travel. At theta = 0 travel is +e2,
    so thrust along -e2 must decelerate the tangential velocity: pitch = +90 deg.
    """
    sim = _direction_sim()
    sim._apply_direction((0.0, -1.0, 0.0))
    assert sim.pitch_rad == pytest.approx(math.pi / 2)


def test_direction_follows_the_local_frame_as_the_vehicle_moves() -> None:
    """The same inertial (stable-member) direction is a different pitch at a different angle."""
    theta = 0.3
    sim = _direction_sim(theta_x=theta)
    # Inertial direction that is exactly local-up at this angle:
    sim._apply_direction((math.cos(theta), math.sin(theta), 0.0))
    assert sim.pitch_rad == pytest.approx(0.0, abs=1e-9)
    # ...and local retro (against travel) at this angle:
    sim._apply_direction((math.sin(theta), -math.cos(theta), 0.0))
    assert sim.pitch_rad == pytest.approx(math.pi / 2)


def test_a_refsmmat_rotation_is_undone_before_pointing() -> None:
    """SM axes are not the reference axes: direction_sm goes through REFSMMAT^T."""
    sim = _direction_sim()
    # SM frame rotated 90 deg about z: SM x = ref y, SM y = -ref x.
    sim.refsmmat = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    sim._apply_direction((0.0, -1.0, 0.0))  # = ref +x = up
    assert sim.pitch_rad == pytest.approx(0.0, abs=1e-12)
