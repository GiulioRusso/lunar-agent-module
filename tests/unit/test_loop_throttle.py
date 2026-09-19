import asyncio
import math
from typing import Any

import pytest

from luminary_agent.agc.actuators import ActuatorState
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import F_MAX_N
from luminary_agent.plant.throttle import MIN_COUNTS, ThrottleActuator
from luminary_agent.sim.frames import IDENTITY, PLANE_IS_XY
from luminary_agent.sim.loop import PipaAxes, Simulation


class FakeDsky:
    program_number = verb_number = noun_number = r1 = r2 = r3 = None


class FakeClient:
    def __init__(self) -> None:
        self.actuators = ActuatorState()
        self.dsky = FakeDsky()
        self.pulses: list[tuple[int, int]] = []

    async def send_pipa_pulses(self, register: int, count: int) -> None:
        self.pulses.append((register, count))


class FakeClock:
    def __init__(self) -> None:
        self.sim_time_s = 0.0

    async def advance(self, dt_s: float) -> None:
        self.sim_time_s += dt_s


def _sim(client: FakeClient, reads: list[int], increments: list[int]) -> Simulation:
    async def reader() -> int:
        reads.append(1)
        return increments[len(reads) - 1]

    return Simulation(
        client,  # type: ignore[arg-type]
        FakeClock(),
        PlanarState(15_000.0, 0.0, 0.0, 1_680.0, 15_000.0),
        PipaAxes(x=0o37, y=0o40, z=0o41),
        PLANE_IS_XY,
        IDENTITY,
        actuator=ThrottleActuator(),
        read_thrust_increment=reader,
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_no_thrust_until_the_agc_turns_the_engine_on() -> None:
    client, reads = FakeClient(), list[int]()
    sim = _sim(client, reads, [])
    rec = run(sim.tick())
    assert rec["thrust_n"] == 0.0 and reads == []


def test_engine_on_starts_at_minimum_throttle_and_burns_propellant() -> None:
    client, reads = FakeClient(), list[int]()
    sim = _sim(client, reads, [])
    client.actuators.engine_on = True
    rec = run(sim.tick())
    assert math.isclose(rec["thrust_n"], 0.10 * F_MAX_N)
    assert sim.state.mass_kg < 15_000.0


def test_thrust_register_is_read_once_per_strobe_not_once_per_tick() -> None:
    client, reads = FakeClient(), list[int]()
    sim = _sim(client, reads, [500, 200])
    client.actuators.engine_on = True

    async def go() -> list[float]:
        thrusts = []
        for _ in range(5):  # no strobe yet
            thrusts.append((await sim.tick())["thrust_n"])
        client.actuators.throttle_strobe_count = 1  # one new AGC command
        for _ in range(5):
            thrusts.append((await sim.tick())["thrust_n"])
        return thrusts

    thrusts = run(go())
    assert len(reads) == 1, "should read on the strobe edge only"
    assert thrusts[4] == pytest.approx(thrusts[0])  # nothing changed before the strobe
    assert thrusts[9] > thrusts[4]  # the increment slewed in afterwards


def test_a_second_strobe_reads_again() -> None:
    client, reads = FakeClient(), list[int]()
    sim = _sim(client, reads, [300, -100])
    client.actuators.engine_on = True

    async def go() -> None:
        await sim.tick()
        client.actuators.throttle_strobe_count = 1
        await sim.tick()
        client.actuators.throttle_strobe_count = 2
        await sim.tick()

    run(go())
    assert len(reads) == 2
    assert sim.actuator is not None
    # 64 counts of slew per 20 ms tick. Tick 2 takes +300 (slews 64, 236 pending); tick 3 takes
    # -100 (136 pending) and slews 64 more: 128 counts above minimum, 72 still pending.
    assert sim.actuator.counts == pytest.approx(MIN_COUNTS + 128)
    assert sim.actuator.pending == pytest.approx(72)


def test_engine_off_again_cuts_thrust() -> None:
    client, reads = FakeClient(), list[int]()
    sim = _sim(client, reads, [])
    client.actuators.engine_on = True
    run(sim.tick())
    client.actuators.engine_on = False
    assert run(sim.tick())["thrust_n"] == 0.0


def test_actuator_without_a_reader_is_rejected() -> None:
    with pytest.raises(ValueError, match="read_thrust_increment"):
        Simulation(
            FakeClient(),  # type: ignore[arg-type]
            FakeClock(),
            PlanarState(1.0, 0.0, 0.0, 0.0, 1.0),
            PipaAxes(0o37, 0o40, 0o41),
            PLANE_IS_XY,
            IDENTITY,
            actuator=ThrottleActuator(),
        )
