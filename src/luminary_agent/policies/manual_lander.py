"""ManualLander: the crew's takeover, flown from the landing radar's truth (plant altitude and
velocities) rather than from the AGC's belief.

wants_manual() is the takeover decision (a fixed rule here: below `takeover_h_m`, or once
Luminary reaches P65 -- the visible "final phase" annunciator). control() then commands
(throttle fraction, thrust pitch) each tick: a vertical-rate schedule against altitude and a
lateral nulling of the velocity *relative to the rotating surface*, inside the DPS throttle
limits (10 %-60 %; the unstable band above it is avoided) and a tilt limit.
"""

from __future__ import annotations

import math

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.propulsion import F_MAX_N, THROTTLE_MAX_VARIABLE, THROTTLE_MIN
from luminary_agent.plant.surface import MOON_RATE_RAD_S

MAX_TILT_RAD = 0.6


class ManualLander:
    name = "manual"

    def __init__(self, takeover_h_m: float = 150.0, tau_v_s: float = 2.0, tau_h_s: float = 4.0):
        self.takeover_h_m = takeover_h_m
        self.tau_v_s = tau_v_s
        self.tau_h_s = tau_h_s

    def wants_manual(self, state: PlanarState, program: int | None) -> bool:
        return state.h_m <= self.takeover_h_m or program == 65

    def control(self, state: PlanarState) -> tuple[float, float]:
        r = R_MOON + state.h_m
        vh = state.xdot_ms - MOON_RATE_RAD_S * r
        v_target = -min(2.0, 0.3 + 0.06 * max(state.h_m, 0.0))
        a_r = (v_target - state.hdot_ms) / self.tau_v_s - state.xdot_ms**2 / r + MU_MOON / r**2
        a_r = max(a_r, 0.1)
        a_t = state.hdot_ms * state.xdot_ms / r - vh / self.tau_h_s
        a_t = max(-a_r * math.tan(MAX_TILT_RAD), min(a_r * math.tan(MAX_TILT_RAD), a_t))
        pitch = math.atan2(-a_t, a_r)
        thrust = state.mass_kg * math.hypot(a_r, a_t)
        throttle = max(THROTTLE_MIN, min(THROTTLE_MAX_VARIABLE, thrust / F_MAX_N))
        return throttle, pitch
