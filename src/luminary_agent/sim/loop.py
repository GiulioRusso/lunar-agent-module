"""One simulation episode: plant + IMU -> AGC -> clock -> recorder (CODE_REVIEW.md Sec.3).

Per tick (dt = 20 ms): integrate the plant under the current control, turn the sensed
specific force into PIPA pulses and feed them to the AGC, advance the clock (which in
stepped mode is what actually lets the AGC execute and consume them), then log the tick.
The loop never touches wall-time; everything time-related goes through the clock.

Throttle: when a ThrottleActuator is supplied the plant thrust is whatever the AGC commands.
Luminary writes a new THRUST *increment* (plant/throttle.py) and stamps TTHROT with the clock; the
loop takes a guidance sample (a ~15 ms core dump) at engine ignition and then every
`guidance_every_ticks`, applies the increment when the stamp has changed, and re-points the
thrust along the freshly-written UNFC/2 every time. Engine on/off comes from CHAN11.
Without an actuator the `throttle` callable is used directly (tests). Once `manual` is set (crew
takeover, sim/executor.py) throttle and pitch come from it and the AGC's commands are ignored.

Out of plane: the plant is planar, but the thrust the AGC commands is not. The out-of-plane
component drives a small lateral channel (z, zdot; linearised about the orbit plane) that the
PIPAs feel, so the AGC's cross-range loop closes instead of winding up on an error the plant cannot
express. The planar and normal components share the same thrust magnitude, so cross-range
steering never creates additional force or consumes a separate propellant budget.

Deliberately absent so far: attitude feedback (CDU angles, jets acting on the vehicle).

The closed loop, one tick (this is the heart of the project):

    plant state --(physics, RK4)--> new state
        |                              |
        | thrust/mass                  +--> record (log + live window)
        v
    IMU model -> PIPA pulses --(TCP socket)--> AGC counters
                                                   |
    clock.advance(dt) --(stdin: STEP n)--> AGC runs Luminary for dt seconds
                                                   |
    AGC channel writes (engine on/off) <--(socket)-+   core dump (THRUST, UNFC/2) every
         and guidance sample ---------------------------> 25 ticks -> throttle actuator + pitch
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import AGC_CYCLES_PER_SECOND
from luminary_agent.agc.guidance import GuidanceSample, read_guidance
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.lunar_orientation import Mat
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.sensors import Imu
from luminary_agent.plant.throttle import ThrottleActuator
from luminary_agent.sim.clock import INITIAL_CYCLES_PER_INSTRUCTION, SimClock, SteppedClock
from luminary_agent.sim.frames import LunarFrame, dot, mat_vec, theta_rad
from luminary_agent.sim.meter import Meter
from luminary_agent.sim.recorder import Recorder

# TYPE_CHECKING is False at run time: this import is only seen by the type checker (mypy), so the
# simulation never imports the viewer code.
if TYPE_CHECKING:  # a window onto the run, never part of it (viz/live.py)
    from luminary_agent.viz.live import LiveFeed


@dataclass(frozen=True)
class PipaAxes:
    """The AGC PIPA register for each stable-member axis: X -> PIPAX, Y -> PIPAY, Z -> PIPAZ."""

    x: int
    y: int
    z: int


class Simulation:
    """One closed-loop run of plant + AGC. Call `await tick()` repeatedly (or `run(duration)`).

    Most arguments are wiring: the AGC client, the clock, the starting state, the frame and
    REFSMMAT that map plant vectors into AGC axes. `throttle`/`pitch_rad` are only used by tests
    without an actuator; a real descent passes `actuator` + `read_guidance_sample`.
    """

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
        dry_mass_kg: float | None = None,
        meter: Meter | None = None,
        live: LiveFeed | None = None,
        site_x_m: float | None = None,
        site_reference_s: float = 0.0,
    ) -> None:
        if actuator is not None and read_guidance_sample is None:
            raise ValueError("an actuator needs read_guidance_sample to hear from the AGC")
        self.site_x_m = site_x_m
        self.site_reference_s = site_reference_s
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
        self.thrust_n = 0.0
        self.actuator = actuator
        self.t_offset_s = t_offset_s  # plant time at clock time zero (epoch to run start)
        self._read_guidance_sample = read_guidance_sample
        self._stamp_seen: int | None = None
        self.guidance_every_ticks = guidance_every_ticks
        self.manual: Callable[[PlanarState], tuple[float, float] | Control] | None = (
            None  # crew takeover
        )
        self.dry_mass_kg = dry_mass_kg  # engine cuts off when propellant is gone
        self.z_m = 0.0  # out-of-plane position (along the orbit normal)
        self.zdot_ms = 0.0
        self.normal_fraction = 0.0  # out-of-plane share of the thrust direction
        self.meter = meter or Meter()  # wall time per section (sim/meter.py)
        self.live = live  # optional live viewer; dropping frames must never slow the run

    def _apply_direction(self, direction_sm: tuple[float, float, float]) -> None:
        """Point the thrust along the AGC's command (perfect pointing -- see agc/guidance.py).

        Stable member -> reference frame (REFSMMAT^T), then onto the plant's local axes at the
        present angle; pitch is measured from local vertical, positive decelerating the
        tangential velocity (plant/dynamics.py). The out-of-plane share is kept in
        `normal_fraction` for the lateral channel.
        """
        m = self.refsmmat
        # REFSMMAT transposed times the vector: stable-member axes -> reference axes.
        ref = (
            m[0][0] * direction_sm[0] + m[1][0] * direction_sm[1] + m[2][0] * direction_sm[2],
            m[0][1] * direction_sm[0] + m[1][1] * direction_sm[1] + m[2][1] * direction_sm[2],
            m[0][2] * direction_sm[0] + m[1][2] * direction_sm[1] + m[2][2] * direction_sm[2],
        )
        # Project onto the plant plane, then rotate into local (radial, tangential) at theta.
        ex, ey = dot(ref, self.frame.e1), dot(ref, self.frame.e2)
        theta = theta_rad(self.state)
        radial = ex * math.cos(theta) + ey * math.sin(theta)
        tangential = -ex * math.sin(theta) + ey * math.cos(theta)
        normal = dot(ref, self.frame.normal)
        in_plane = math.hypot(radial, tangential)
        # A near-zero in-plane part (thrust nearly along the normal) keeps the last pitch instead
        # of flipping on numerical noise.
        if in_plane > 1e-3 * abs(normal) and in_plane > 1e-9:
            self.pitch_rad = math.atan2(-tangential, radial)
        self.normal_fraction = normal / (math.hypot(in_plane, normal) or 1.0)

    async def _service_throttle(self) -> float:
        """Fold the AGC's engine and throttle commands into the actuator; return throttle."""
        assert self.actuator is not None and self._read_guidance_sample is not None
        act = self.client.actuators  # engine on/off as last seen on the socket
        engine_just_lit = act.engine_on and not self.actuator.engine_on
        if act.engine_on != self.actuator.engine_on:
            self.actuator.set_engine(act.engine_on)
            if engine_just_lit:
                self._stamp_seen = None  # a command stamped before ignition is not ours to apply
        # Reading guidance costs a core dump (~15 ms), so only every N ticks (25 = 0.5 s).
        due = act.engine_on and self.ticks % self.guidance_every_ticks == 0
        if engine_just_lit or due:
            with self.meter.section("guidance"):
                sample = await self._read_guidance_sample()
            # A changed TTHROT stamp = Luminary issued a new throttle increment since last look.
            if self._stamp_seen is not None and sample.command_stamp != self._stamp_seen:
                self.actuator.command(sample.thrust_increment_counts)
            self._stamp_seen = sample.command_stamp
            if sample.thrust_direction_sm is not None:
                self._apply_direction(sample.thrust_direction_sm)
        self.actuator.step(self.dt_s)
        return self.actuator.throttle_fraction

    async def tick(self) -> dict[str, Any]:
        """Advance the whole system by dt_s (20 ms) and return the tick's log record."""
        # 1. Decide throttle and pitch: manual controller, AGC commands, or the test callable.
        if self.manual is not None:
            manual_control = self.manual(self.state)
            if isinstance(manual_control, Control):
                throttle, self.pitch_rad = manual_control.throttle, manual_control.pitch_rad
                self.normal_fraction = manual_control.normal_fraction
            else:  # compatibility with planar control callbacks
                throttle, self.pitch_rad = manual_control
                self.normal_fraction = 0.0
        else:
            throttle = await self._service_throttle() if self.actuator else self.throttle()
        if self.dry_mass_kg is not None and self.state.mass_kg <= self.dry_mass_kg:
            throttle = 0.0  # out of propellant: the engine can burn nothing
        control = Control(
            throttle=throttle, pitch_rad=self.pitch_rad, normal_fraction=self.normal_fraction
        )
        thrust_n, _ = self.engine.thrust_and_mdot(control.throttle)
        self.thrust_n = thrust_n

        # An accelerometer senses specific force (thrust / mass), never gravity. It sits on an
        # inertially-fixed stable member, so rotate the local (radial, tangential) thrust
        # acceleration into the reference frame at the pre-step angle, then into stable-member
        # axes with REFSMMAT.
        with self.meter.section("plant"):
            sf_radial = (
                thrust_n
                * control.in_plane_fraction
                * math.cos(control.pitch_rad)
                / self.state.mass_kg
            )
            sf_tangential = (
                -thrust_n
                * control.in_plane_fraction
                * math.sin(control.pitch_rad)
                / self.state.mass_kg
            )
            sf_normal = thrust_n * self.normal_fraction / self.state.mass_kg
            sf_ref = self.frame.specific_force_ref(
                sf_radial, sf_tangential, theta_rad(self.state), sf_normal
            )
            sf_sm = mat_vec(self.refsmmat, sf_ref)
            # Out-of-plane channel: thrust sideways minus a restoring gravity term, integrated
            # with a simple constant-acceleration step.
            r = R_MOON + self.state.h_m
            z_acc = sf_normal - MU_MOON / r**3 * self.z_m
            self.z_m += self.zdot_ms * self.dt_s + 0.5 * z_acc * self.dt_s**2
            self.zdot_ms += z_acc * self.dt_s
            self.state = step(self.state, control, self.engine, self.dt_s)  # 2. physics
            (px, py, pz), _ = self.imu.sample(sf_sm, 0.0, self.dt_s)  # 3. accelerometers

        with self.meter.section("pipa"):  # 4. send the pulses to the AGC
            await self.client.send_pipa_pulses(self.pipa_axes.x, px)
            await self.client.send_pipa_pulses(self.pipa_axes.y, py)
            await self.client.send_pipa_pulses(self.pipa_axes.z, pz)

        with self.meter.section("step"):  # 5. let the AGC run for dt (it reads the pulses)
            await self.clock.advance(self.dt_s)
        self.ticks += 1

        with self.meter.section("record"):  # 6. log + live window
            record = self._record(thrust_n, (px, py, pz))
            if self.recorder is not None:
                self.recorder.tick(record)
            if self.live is not None:
                self.live.publish_tick(record)
        return record

    def _record(self, thrust_n: float, pulses: tuple[int, int, int]) -> dict[str, Any]:
        """One JSON-ready line of the episode log (the fields the replay viewer reads)."""
        from luminary_agent.plant.surface import site_position_m

        dsky = self.client.dsky
        act = self.client.actuators
        return {
            "t": round(self.t_offset_s + self.clock.sim_time_s, 6),
            "h_m": self.state.h_m,
            "x_m": self.state.x_m,
            "z_m": self.z_m,
            "zdot_ms": self.zdot_ms,
            "target_downrange_m": (
                self.state.x_m
                - site_position_m(
                    self.site_x_m, self.t_offset_s + self.clock.sim_time_s - self.site_reference_s
                )
                if self.site_x_m is not None
                else None
            ),
            "hdot_ms": self.state.hdot_ms,
            "vt_ms": self.state.xdot_ms,
            "mass_kg": self.state.mass_kg,
            "thrust_n": thrust_n,
            "mode": "auto" if self.manual is None else "manual",
            "pitch_deg": math.degrees(self.pitch_rad),
            "normal_fraction": round(self.normal_fraction, 4),
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
        cpi = (
            self.clock.cycles_per_instruction
            if isinstance(self.clock, SteppedClock)
            else INITIAL_CYCLES_PER_INSTRUCTION
        )
        seconds = instructions * cpi / AGC_CYCLES_PER_SECOND
        for _ in range(max(1, round(seconds / self.dt_s))):
            await self.tick()

    async def run(self, duration_s: float) -> None:
        """Tick for `duration_s` simulated seconds."""
        for _ in range(round(duration_s / self.dt_s)):
            await self.tick()


def stepped_guidance_reader(
    agc: AgcProcess, symbols: SymbolTable
) -> Callable[[], Awaitable[GuidanceSample]]:
    """Read THRUST and UNFC/2 at the pause boundary of a stepped run (one ~15 ms core dump)."""

    # A closure: `read` remembers agc and symbols, so the Simulation can call it with no args.
    async def read() -> GuidanceSample:
        return read_guidance(await agc.coredump(), symbols)

    return read
