"""Plant <-> AGC reference frame.

The plant is planar in polar form (altitude, arc-length downrange, vertical and tangential
velocity). The AGC works in a Moon-centred inertial frame (MCI), and -- with REFSMMAT set to
the identity -- the stable member is aligned with it, so the IMU's PIPAs measure specific
force along MCI X and Y. Convention fixed here and nowhere else:

  * the orbit lies in the MCI X-Y plane; Z (out of plane) is always zero;
  * at t0 (downrange x = 0) the local vertical is +X and the direction of travel is +Y;
  * theta = x / R_moon is the angle swept from t0; r_hat = (cos t, sin t, 0),
    t_hat = (-sin t, cos t, 0).

Moon rotation (~2.7e-6 rad/s) is ignored: over a ~12 minute descent it is ~2 milliradians,
far below anything this plant resolves.
"""

from __future__ import annotations

import math

from luminary_agent.agc.state_vector import StateVector
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import R_MOON


def theta_rad(state: PlanarState) -> float:
    return state.x_m / R_MOON


def inertial_vector(radial: float, tangential: float, theta: float) -> tuple[float, float, float]:
    """A vector given by (radial, tangential) components, in MCI axes."""
    c, s = math.cos(theta), math.sin(theta)
    return (radial * c - tangential * s, radial * s + tangential * c, 0.0)


def inertial_state_vector(state: PlanarState, t_cs: float) -> StateVector:
    theta = theta_rad(state)
    return StateVector(
        r_m=inertial_vector(R_MOON + state.h_m, 0.0, theta),
        v_ms=inertial_vector(state.hdot_ms, state.xdot_ms, theta),
        t_cs=t_cs,
    )
