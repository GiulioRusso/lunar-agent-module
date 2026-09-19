"""One simulation episode: plant + IMU -> AGC -> clock -> recorder (APOLLO_AGENT_PLAN.md Sec.3).

Per tick (dt = 20 ms): integrate the plant under the current control, turn the sensed
specific force into PIPA pulses and feed them to the AGC, advance the clock (which in
stepped mode is what actually lets the AGC execute and consume them), then log the tick.
The loop never touches wall-time; everything time-related goes through the clock.

Deliberately absent so far: the AGC-commanded throttle and the attitude feedback. The
throttle source is a callable so the AGC-derived one (core dump of the THRUST register,
which still needs a counts->newtons calibration) can be dropped in without touching this.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.sensors import PlanarImu
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
    ) -> None:
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

    async def tick(self) -> dict[str, Any]:
        control = Control(throttle=self.throttle(), pitch_rad=self.pitch_rad)
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
