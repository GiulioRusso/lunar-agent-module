"""One simulation episode: plant + IMU -> AGC -> clock -> recorder (APOLLO_AGENT_PLAN.md Sec.3).

Per tick (dt = 20 ms): integrate the plant under the current control, turn the sensed
specific force into PIPA pulses and feed them to the AGC, advance the clock (which in
stepped mode is what actually lets the AGC execute and consume them), then log the tick.
The loop never touches wall-time; everything time-related goes through the clock.

Throttle: when a ThrottleActuator is supplied the plant thrust is whatever the AGC commands.
Luminary writes a new THRUST *increment* (plant/throttle.py) and stamps TTHROT with the clock; the
loop takes a guidance sample (a ~15 ms core dump) at engine ignition and then every
`guidance_every_ticks`, applies the increment when the stamp has changed, and re-points the
thrust along the freshly-written UNFC/2 every time. Engine on/off comes from CHAN11.
Without an actuator the `throttle` callable is used directly (tests, null baselines).

Deliberately absent so far: attitude feedback (CDU angles, jets acting on the vehicle).
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import AGC_CYCLES_PER_SECOND
from luminary_agent.agc.guidance import GuidanceSample, read_guidance
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.lunar_orientation import Mat
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.sensors import Imu
from luminary_agent.plant.throttle import ThrottleActuator
from luminary_agent.sim.clock import SimClock, SteppedClock
from luminary_agent.sim.frames import LunarFrame, dot, mat_vec, theta_rad
from luminary_agent.sim.recorder import Recorder


@dataclass(frozen=True)
class PipaAxes:
    """The AGC PIPA register for each stable-member axis: X -> PIPAX, Y -> PIPAY, Z -> PIPAZ."""

    x: int
    y: int
    z: int


class Simulation:
    def __init__(
        self,
        client: AgcClient,
        clock: SimClock,
        state: PlanarState,
        pipa_axes: PipaAxes,
        frame: LunarFrame,
        refsmmat: Mat,
        engine: DescentEngine | None = None,
        recorder: Recorder | None = None,
        throttle: Callable[[], float] = lambda: 0.0,
        pitch_rad: float = 0.0,
        dt_s: float = DT_S,
        actuator: ThrottleActuator | None = None,
        read_guidance_sample: Callable[[], Awaitable[GuidanceSample]] | None = None,
        t_offset_s: float = 0.0,
        guidance_every_ticks: int = 25,
    ) -> None:
        if actuator is not None and read_guidance_sample is None:
            raise ValueError("an actuator needs read_guidance_sample to hear from the AGC")
        self.client = client
        self.clock = clock
        self.state = state
        self.pipa_axes = pipa_axes
        self.frame = frame
        self.refsmmat = refsmmat
        self.engine = engine or DescentEngine()
        self.recorder = recorder
        self.throttle = throttle
        self.pitch_rad = pitch_rad
        self.dt_s = dt_s
        self.imu = Imu()
        self.ticks = 0
        self.actuator = actuator
        self.t_offset_s = t_offset_s  # plant time at clock time zero (epoch to run start)
        self._read_guidance_sample = read_guidance_sample
        self._stamp_seen: int | None = None
        self.guidance_every_ticks = guidance_every_ticks

    def _apply_direction(self, direction_sm: tuple[float, float, float]) -> None:
        """Point the thrust along the AGC's command (perfect pointing -- see agc/guidance.py).

        Stable member -> reference frame (REFSMMAT^T), then onto the plant's local axes at the
        present angle; pitch is measured from local vertical, positive decelerating the
        tangential velocity (plant/dynamics.py). Any out-of-plane component is dropped.
        """
        m = self.refsmmat
        ref = (
            m[0][0] * direction_sm[0] + m[1][0] * direction_sm[1] + m[2][0] * direction_sm[2],
            m[0][1] * direction_sm[0] + m[1][1] * direction_sm[1] + m[2][1] * direction_sm[2],
            m[0][2] * direction_sm[0] + m[1][2] * direction_sm[1] + m[2][2] * direction_sm[2],
        )
        ex, ey = dot(ref, self.frame.e1), dot(ref, self.frame.e2)
        theta = theta_rad(self.state)
        radial = ex * math.cos(theta) + ey * math.sin(theta)
        tangential = -ex * math.sin(theta) + ey * math.cos(theta)
        self.pitch_rad = math.atan2(-tangential, radial)

    async def _service_throttle(self) -> float:
        """Fold the AGC's engine and throttle commands into the actuator; return throttle."""
        assert self.actuator is not None and self._read_guidance_sample is not None
        act = self.client.actuators
        engine_just_lit = act.engine_on and not self.actuator.engine_on
        if act.engine_on != self.actuator.engine_on:
            self.actuator.set_engine(act.engine_on)
            if engine_just_lit:
                self._stamp_seen = None  # a command stamped before ignition is not ours to apply
        due = act.engine_on and self.ticks % self.guidance_every_ticks == 0
        if engine_just_lit or due:
            sample = await self._read_guidance_sample()
            if self._stamp_seen is not None and sample.command_stamp != self._stamp_seen:
                self.actuator.command(sample.thrust_increment_counts)
            self._stamp_seen = sample.command_stamp
            if sample.thrust_direction_sm is not None:
                self._apply_direction(sample.thrust_direction_sm)
        self.actuator.step(self.dt_s)
        return self.actuator.throttle_fraction

    async def tick(self) -> dict[str, Any]:
        throttle = await self._service_throttle() if self.actuator else self.throttle()
        control = Control(throttle=throttle, pitch_rad=self.pitch_rad)
        thrust_n, _ = self.engine.thrust_and_mdot(control.throttle)

        # An accelerometer senses specific force (thrust / mass), never gravity. It sits on an
        # inertially-fixed stable member, so rotate the local (radial, tangential) thrust
        # acceleration into the reference frame at the pre-step angle, then into stable-member
        # axes with REFSMMAT.
        sf_radial = thrust_n * math.cos(control.pitch_rad) / self.state.mass_kg
        sf_tangential = -thrust_n * math.sin(control.pitch_rad) / self.state.mass_kg
        sf_ref = self.frame.specific_force_ref(sf_radial, sf_tangential, theta_rad(self.state))
        sf_sm = mat_vec(self.refsmmat, sf_ref)
        self.state = step(self.state, control, self.engine, self.dt_s)

        (px, py, pz), _ = self.imu.sample(sf_sm, 0.0, self.dt_s)
        await self.client.send_pipa_pulses(self.pipa_axes.x, px)
        await self.client.send_pipa_pulses(self.pipa_axes.y, py)
        await self.client.send_pipa_pulses(self.pipa_axes.z, pz)

        await self.clock.advance(self.dt_s)
        self.ticks += 1

        record = self._record(thrust_n, (px, py, pz))
        if self.recorder is not None:
            self.recorder.tick(record)
        return record

    def _record(self, thrust_n: float, pulses: tuple[int, int, int]) -> dict[str, Any]:
        dsky = self.client.dsky
        act = self.client.actuators
        return {
            "t": round(self.t_offset_s + self.clock.sim_time_s, 6),
            "h_m": self.state.h_m,
            "x_m": self.state.x_m,
            "hdot_ms": self.state.hdot_ms,
            "vt_ms": self.state.xdot_ms,
            "mass_kg": self.state.mass_kg,
            "thrust_n": thrust_n,
            "pitch_deg": math.degrees(self.pitch_rad),
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

    async def advance_instructions(self, instructions: int) -> None:
        """Let `instructions` AGC instructions elapse *with the plant alongside* -- the hook to
        hand to SteppedDsky so that key presses advance both together. Rounded to whole ticks.
        """
        cpi = self.clock.cycles_per_instruction if isinstance(self.clock, SteppedClock) else 1.62
        seconds = instructions * cpi / AGC_CYCLES_PER_SECOND
        for _ in range(max(1, round(seconds / self.dt_s))):
            await self.tick()

    async def run(self, duration_s: float) -> None:
        for _ in range(round(duration_s / self.dt_s)):
            await self.tick()


def stepped_guidance_reader(
    agc: AgcProcess, symbols: SymbolTable
) -> Callable[[], Awaitable[GuidanceSample]]:
    """Read THRUST and UNFC/2 at the pause boundary of a stepped run (one ~15 ms core dump)."""

    async def read() -> GuidanceSample:
        return read_guidance(await agc.coredump(), symbols)

    return read
