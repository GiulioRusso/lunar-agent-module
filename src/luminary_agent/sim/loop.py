"""One simulation episode: plant + IMU -> AGC -> clock -> recorder (APOLLO_AGENT_PLAN.md Sec.3).

Per tick (dt = 20 ms): integrate the plant under the current control, turn the sensed
specific force into PIPA pulses and feed them to the AGC, advance the clock (which in
stepped mode is what actually lets the AGC execute and consume them), then log the tick.
The loop never touches wall-time; everything time-related goes through the clock.

Throttle: when a ThrottleActuator is supplied the plant thrust is whatever the AGC commands.
Luminary strobes CHAN14 bit 4 each time it writes a new THRUST *increment* (plant/throttle.py);
on each new strobe the loop reads the register once (a ~15 ms core dump, affordable at ~1 Hz)
and feeds the increment to the actuator, which slews it in. Engine on/off comes from CHAN11.
Without an actuator the `throttle` callable is used directly (tests, null baselines).

Deliberately absent so far: attitude feedback (CDU angles, jets acting on the vehicle).
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import THRUST_REGISTER
from luminary_agent.agc.process import AgcProcess
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.sensors import PlanarImu
from luminary_agent.plant.throttle import ThrottleActuator
from luminary_agent.sim.clock import SimClock, SteppedClock
from luminary_agent.sim.frames import inertial_vector, theta_rad
from luminary_agent.sim.recorder import Recorder


@dataclass(frozen=True)
class PipaAxes:
    """Which AGC PIPA register carries each inertial in-plane axis. With REFSMMAT = identity
    the stable member is the MCI frame (sim/frames.py): X -> PIPAX, Y -> PIPAY.
    """

    x: int
    y: int


class Simulation:
    def __init__(
        self,
        client: AgcClient,
        clock: SimClock,
        state: PlanarState,
        pipa_axes: PipaAxes,
        engine: DescentEngine | None = None,
        recorder: Recorder | None = None,
        throttle: Callable[[], float] = lambda: 0.0,
        pitch_rad: float = 0.0,
        dt_s: float = DT_S,
        actuator: ThrottleActuator | None = None,
        read_thrust_increment: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        if actuator is not None and read_thrust_increment is None:
            raise ValueError("an actuator needs read_thrust_increment to hear from the AGC")
        self.client = client
        self.clock = clock
        self.state = state
        self.pipa_axes = pipa_axes
        self.engine = engine or DescentEngine()
        self.recorder = recorder
        self.throttle = throttle
        self.pitch_rad = pitch_rad
        self.dt_s = dt_s
        self.imu = PlanarImu()
        self.ticks = 0
        self.actuator = actuator
        self._read_thrust_increment = read_thrust_increment
        self._strobes_seen = 0

    async def _service_throttle(self) -> float:
        """Fold the AGC's engine and throttle commands into the actuator; return throttle."""
        assert self.actuator is not None and self._read_thrust_increment is not None
        act = self.client.actuators
        if act.engine_on != self.actuator.engine_on:
            self.actuator.set_engine(act.engine_on)
        if act.throttle_strobe_count != self._strobes_seen:
            self._strobes_seen = act.throttle_strobe_count
            self.actuator.command(await self._read_thrust_increment())
        self.actuator.step(self.dt_s)
        return self.actuator.throttle_fraction

    async def tick(self) -> dict[str, Any]:
        throttle = await self._service_throttle() if self.actuator else self.throttle()
        control = Control(throttle=throttle, pitch_rad=self.pitch_rad)
        thrust_n, _ = self.engine.thrust_and_mdot(control.throttle)

        # An accelerometer senses specific force (thrust / mass), never gravity, and the PIPAs
        # sit on an inertially-fixed stable member: rotate the local (radial, tangential)
        # thrust acceleration into MCI axes at the pre-step angle.
        sf_radial = thrust_n * math.cos(control.pitch_rad) / self.state.mass_kg
        sf_tangential = -thrust_n * math.sin(control.pitch_rad) / self.state.mass_kg
        sf_x, sf_y, _ = inertial_vector(sf_radial, sf_tangential, theta_rad(self.state))
        self.state = step(self.state, control, self.engine, self.dt_s)

        pulses_x, pulses_y, _ = self.imu.sample(sf_x, sf_y, 0.0, self.dt_s)
        await self.client.send_pipa_pulses(self.pipa_axes.x, pulses_x)
        await self.client.send_pipa_pulses(self.pipa_axes.y, pulses_y)

        await self.clock.advance(self.dt_s)
        self.ticks += 1

        record = self._record(thrust_n, (pulses_x, pulses_y))
        if self.recorder is not None:
            self.recorder.tick(record)
        return record

    def _record(self, thrust_n: float, pulses: tuple[int, int]) -> dict[str, Any]:
        dsky = self.client.dsky
        act = self.client.actuators
        return {
            "t": round(self.clock.sim_time_s, 6),
            "h_m": self.state.h_m,
            "x_m": self.state.x_m,
            "hdot_ms": self.state.hdot_ms,
            "vt_ms": self.state.xdot_ms,
            "mass_kg": self.state.mass_kg,
            "thrust_n": thrust_n,
            "pipa_pulses": list(pulses),
            "dsky": {
                "prog": dsky.program_number,
                "verb": dsky.verb_number,
                "noun": dsky.noun_number,
                "r1": dsky.r1,
                "r2": dsky.r2,
                "r3": dsky.r3,
            },
            "engine_on": act.engine_on,
            "jets": [act.pitch_jets, act.roll_jets],
            "throttle_strobes": act.throttle_strobe_count,
            "clock_drift_s": self.clock.drift_s if isinstance(self.clock, SteppedClock) else None,
        }

    async def run(self, duration_s: float) -> None:
        for _ in range(round(duration_s / self.dt_s)):
            await self.tick()


def stepped_thrust_reader(agc: AgcProcess) -> Callable[[], Awaitable[int]]:
    """Read the AGC's THRUST register (a signed thrust increment, in counts) at the pause
    boundary of a stepped run.
    """

    async def read() -> int:
        return (await agc.coredump()).erasable_signed(*THRUST_REGISTER)

    return read
