"""ManualController: what the crew's hands do once they have throttle and attitude (P67).

It flies from the plant's truth (a radar's view, not the AGC's belief): a vertical-rate target
(a schedule against altitude unless an agent commands one) and lateral nulling of the velocity
*relative to the rotating surface*, inside the DPS throttle limits (10 %-60 %; the unstable band
above is avoided) and a tilt limit. An agent steers it through targets, never raw throttle.
"""

from __future__ import annotations

import math

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.propulsion import F_MAX_N, THROTTLE_MAX_VARIABLE, THROTTLE_MIN
from luminary_agent.plant.surface import MOON_RATE_RAD_S

MAX_TILT_RAD = 0.6
MAX_DESCENT_RATE_MS = 6.0  # commanded descent rates are clamped to [-6, 0] m/s
MAX_HORIZONTAL_TARGET_MS = 5.0


class ManualController:
    def __init__(self, tau_v_s: float = 2.0, tau_h_s: float = 4.0) -> None:
        self.tau_v_s = tau_v_s
        self.tau_h_s = tau_h_s
        self.descent_rate_ms: float | None = None  # None: the altitude schedule
        self.horizontal_ms = 0.0  # target velocity relative to the surface

    def set_targets(self, descent_rate_ms: float | None, horizontal_ms: float) -> str:
        """Set targets, clamped to safe ranges; returns a note describing any clamping."""
        note = ""
        if descent_rate_ms is not None:
            c = max(-MAX_DESCENT_RATE_MS, min(0.0, descent_rate_ms))
            note += f"descent_rate clamped {descent_rate_ms}->{c}; " if c != descent_rate_ms else ""
            descent_rate_ms = c
        h = max(-MAX_HORIZONTAL_TARGET_MS, min(MAX_HORIZONTAL_TARGET_MS, horizontal_ms))
        note += f"horizontal clamped {horizontal_ms}->{h}; " if h != horizontal_ms else ""
        self.descent_rate_ms, self.horizontal_ms = descent_rate_ms, h
        return note.rstrip("; ")

    def control(self, state: PlanarState) -> tuple[float, float]:
        r = R_MOON + state.h_m
        vh = state.xdot_ms - MOON_RATE_RAD_S * r
        v_target = self.descent_rate_ms
        if v_target is None:
            v_target = -min(2.0, 0.3 + 0.06 * max(state.h_m, 0.0))
        a_r = (v_target - state.hdot_ms) / self.tau_v_s - state.xdot_ms**2 / r + MU_MOON / r**2
        a_r = max(a_r, 0.1)
        a_t = state.hdot_ms * state.xdot_ms / r - (vh - self.horizontal_ms) / self.tau_h_s
        limit = a_r * math.tan(MAX_TILT_RAD)
        a_t = max(-limit, min(limit, a_t))
        pitch = math.atan2(-a_t, a_r)
        thrust = state.mass_kg * math.hypot(a_r, a_t)
        throttle = max(THROTTLE_MIN, min(THROTTLE_MAX_VARIABLE, thrust / F_MAX_N))
        return throttle, pitch
