"""ManualController: what the crew's hands do once they have throttle and attitude (P67).

It flies from the plant's truth (a radar's view, not the AGC's belief): a vertical-rate target
(a schedule against altitude unless an agent commands one) and lateral nulling of the velocity
*relative to the rotating surface*, inside the DPS throttle limits (10 %-60 %; the unstable band
above is avoided) and a tilt limit. An agent steers it through targets, never raw throttle.

Control law in plain words: "I want to descend at v_target; I am descending at hdot; close the
gap in tau_v seconds" gives a wanted vertical acceleration; the same for horizontal speed.
Add back gravity (minus the centrifugal relief), convert the wanted acceleration vector into
throttle (its length * mass / max thrust) and pitch (its angle from vertical).
"""

from __future__ import annotations

import math

from luminary_agent.plant.dynamics import Control, PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.propulsion import F_MAX_N, THROTTLE_MAX_VARIABLE, THROTTLE_MIN
from luminary_agent.plant.surface import MOON_RATE_RAD_S

MAX_TILT_RAD = 0.6  # ~34 degrees from vertical
MAX_DESCENT_RATE_MS = 6.0  # commanded descent rates are clamped to [-6, 0] m/s
MAX_HORIZONTAL_TARGET_MS = 5.0


class ManualController:
    """Simple proportional controller standing in for the crew's hands."""

    def __init__(self, tau_v_s: float = 2.0, tau_h_s: float = 4.0) -> None:
        # tau_*: response time constants. Smaller = more aggressive corrections.
        self.tau_v_s = tau_v_s
        self.tau_h_s = tau_h_s
        self.descent_rate_ms: float | None = None  # None: the altitude schedule
        self.horizontal_ms = 0.0  # target velocity relative to the surface
        self.cross_ms = 0.0  # target cross-range velocity

    def set_targets(
        self, descent_rate_ms: float | None, horizontal_ms: float, cross_ms: float = 0.0
    ) -> str:
        """Set targets, clamped to safe ranges; returns a note describing any clamping."""
        for name, value in (
            ("descent_rate_ms", descent_rate_ms),
            ("horizontal_ms", horizontal_ms),
            ("cross_ms", cross_ms),
        ):
            if value is None and name == "descent_rate_ms":
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number")
        note = ""
        if descent_rate_ms is not None:
            c = max(-MAX_DESCENT_RATE_MS, min(0.0, descent_rate_ms))
            note += f"descent_rate clamped {descent_rate_ms}->{c}; " if c != descent_rate_ms else ""
            descent_rate_ms = c
        h = max(-MAX_HORIZONTAL_TARGET_MS, min(MAX_HORIZONTAL_TARGET_MS, horizontal_ms))
        note += f"horizontal clamped {horizontal_ms}->{h}; " if h != horizontal_ms else ""
        cross = max(-MAX_HORIZONTAL_TARGET_MS, min(MAX_HORIZONTAL_TARGET_MS, cross_ms))
        note += f"cross clamped {cross_ms}->{cross}; " if cross != cross_ms else ""
        self.descent_rate_ms, self.horizontal_ms, self.cross_ms = descent_rate_ms, h, cross
        return note.rstrip("; ")

    def control(self, state: PlanarState) -> tuple[float, float]:
        """Planar compatibility adapter; the simulation uses control_3d for cross-range feedback."""
        control = self.control_3d(state, 0.0, 0.0)
        return control.throttle, control.pitch_rad

    def control_3d(self, state: PlanarState, z_m: float, zdot_ms: float) -> Control:
        """One thrust vector, sharing a tilt and thrust budget across both horizontal axes."""
        r = R_MOON + state.h_m
        vh = state.xdot_ms - MOON_RATE_RAD_S * r  # horizontal speed over the ground
        v_target = self.descent_rate_ms
        if v_target is None:
            # Default schedule: slower as the ground nears (-2 m/s high up, -0.3 m/s at contact).
            v_target = -min(2.0, 0.3 + 0.06 * max(state.h_m, 0.0))
        # Wanted radial (up) acceleration: close the rate gap + cancel gravity - centrifugal.
        a_r = (v_target - state.hdot_ms) / self.tau_v_s - state.xdot_ms**2 / r + MU_MOON / r**2
        a_r = max(a_r, 0.1)  # always some upward thrust (the engine cannot pull down)
        # Wanted tangential acceleration: close the horizontal-speed gap (+ a Coriolis-like term).
        a_t = state.hdot_ms * state.xdot_ms / r - (vh - self.horizontal_ms) / self.tau_h_s
        a_z = MU_MOON / r**3 * z_m - (zdot_ms - self.cross_ms) / self.tau_h_s
        limit = a_r * math.tan(MAX_TILT_RAD)
        sideways = math.hypot(a_t, a_z)
        if sideways > limit:
            scale = limit / sideways
            a_t *= scale
            a_z *= scale
        pitch = math.atan2(-a_t, a_r)
        acceleration = math.hypot(a_r, a_t, a_z)
        thrust = state.mass_kg * acceleration
        throttle = max(THROTTLE_MIN, min(THROTTLE_MAX_VARIABLE, thrust / F_MAX_N))
        return Control(throttle, pitch, a_z / acceleration)
