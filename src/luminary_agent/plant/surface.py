"""Surface-relative quantities at touchdown.

Luminary steers to zero velocity *relative to the rotating surface* (VGU = V - WM x R), so the
plant's inertial tangential speed at touchdown is not zero but the surface's own speed,
omega * (R + h) ~ 4.6 m/s. The plant's physics is inertial and needs no correction; only the
*judgement* of a landing does.
"""

from __future__ import annotations

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import R_MOON

# CONTROLLED_CONSTANTS.agc: MOONRATE 2DEC* .26616994890062991 E-7 B+19 (RAD/CS).
MOON_RATE_RAD_S = 0.26616994890062991e-7 * 100.0


def horizontal_speed_relative_to_surface(state: PlanarState) -> float:
    """Tangential velocity minus the surface's own velocity at this altitude (m/s)."""
    return state.xdot_ms - MOON_RATE_RAD_S * (R_MOON + state.h_m)


def downrange_error_m(state: PlanarState, site_angle_rad: float) -> float:
    """Along-track distance past (+) or short of (-) the site, on the surface."""
    return state.x_m - site_angle_rad * R_MOON
