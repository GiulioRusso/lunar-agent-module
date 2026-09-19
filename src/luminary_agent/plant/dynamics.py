"""3-DoF planar descent dynamics over a spherical Moon: altitude, downrange, their rates,
and vehicle mass.

Deliberately the *first* plant (APOLLO_AGENT_PLAN.md Sec.5, Phase 1, and Sec.9's trap
"6-DoF before 3-DoF closes"): point-mass, thrust vector set directly by a commanded
pitch angle, no attitude dynamics. This is enough to close the loop against Luminary's
throttle/jet channels; 6-DoF with RCS jet torques is a later, additive step once this
is validated against analytic cases (see tests/unit/test_dynamics.py).

State is (h, x, hdot, xdot, mass): altitude above the surface, downrange arc length along
the surface, vertical velocity, *tangential* velocity, and current vehicle mass. The Moon is
a sphere, not a plane: at PDI the horizontal speed is ~1.7 km/s and the centrifugal term
v^2/r (~1.66 m/s^2) nearly cancels lunar gravity (~1.62 m/s^2), so a flat-surface model
would plunge a vehicle that is in fact nearly in orbit.

Integrated with fixed-step RK4 at 50 Hz, control (throttle, pitch) held constant over the
step -- a zero-order hold, matching a real digital control loop running at a fixed rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from luminary_agent.plant.gravity import R_MOON, g
from luminary_agent.plant.propulsion import DescentEngine

SIM_HZ = 50.0
DT_S = 1.0 / SIM_HZ


@dataclass(frozen=True)
class PlanarState:
    h_m: float  # altitude above the surface
    x_m: float  # downrange position
    hdot_ms: float  # vertical velocity, positive up
    xdot_ms: float  # tangential velocity, positive in the direction of travel
    mass_kg: float


@dataclass(frozen=True)
class Control:
    throttle: float  # commanded fraction [0, 1], resolved by DescentEngine
    pitch_rad: float  # thrust-vector angle from local vertical; positive decelerates xdot


def derivative(state: PlanarState, control: Control, engine: DescentEngine) -> PlanarState:
    """dState/dt as a PlanarState-shaped tuple of rates (reusing the dataclass as a
    convenient 5-vector -- these fields are rates, not state, only for this function).

    Polar form about the Moon's centre, r = R + h, vt = tangential speed:
        h'  = hdot
        x'  = vt * R / r                      (x is arc length at the surface)
        hdot' = vt^2/r - g(h) + a_radial      (centrifugal relief)
        vt' = -hdot * vt / r + a_tangential   (angular momentum: d(r*vt)/dt = r*a_t)
    """
    thrust_n, mdot = engine.thrust_and_mdot(control.throttle)
    a_radial = thrust_n * math.cos(control.pitch_rad) / state.mass_kg
    a_tangential = -thrust_n * math.sin(control.pitch_rad) / state.mass_kg
    r = R_MOON + state.h_m
    return PlanarState(
        h_m=state.hdot_ms,
        x_m=state.xdot_ms * R_MOON / r,
        hdot_ms=state.xdot_ms**2 / r - g(state.h_m) + a_radial,
        xdot_ms=-state.hdot_ms * state.xdot_ms / r + a_tangential,
        mass_kg=-mdot,
    )


def _add_scaled(a: PlanarState, b: PlanarState, scale: float) -> PlanarState:
    return PlanarState(
        h_m=a.h_m + scale * b.h_m,
        x_m=a.x_m + scale * b.x_m,
        hdot_ms=a.hdot_ms + scale * b.hdot_ms,
        xdot_ms=a.xdot_ms + scale * b.xdot_ms,
        mass_kg=a.mass_kg + scale * b.mass_kg,
    )


def step(
    state: PlanarState, control: Control, engine: DescentEngine, dt_s: float = DT_S
) -> PlanarState:
    """One fixed-step RK4 integration step."""
    k1 = derivative(state, control, engine)
    k2 = derivative(_add_scaled(state, k1, dt_s / 2), control, engine)
    k3 = derivative(_add_scaled(state, k2, dt_s / 2), control, engine)
    k4 = derivative(_add_scaled(state, k3, dt_s), control, engine)
    return PlanarState(
        h_m=state.h_m + (dt_s / 6) * (k1.h_m + 2 * k2.h_m + 2 * k3.h_m + k4.h_m),
        x_m=state.x_m + (dt_s / 6) * (k1.x_m + 2 * k2.x_m + 2 * k3.x_m + k4.x_m),
        hdot_ms=state.hdot_ms
        + (dt_s / 6) * (k1.hdot_ms + 2 * k2.hdot_ms + 2 * k3.hdot_ms + k4.hdot_ms),
        xdot_ms=state.xdot_ms
        + (dt_s / 6) * (k1.xdot_ms + 2 * k2.xdot_ms + 2 * k3.xdot_ms + k4.xdot_ms),
        mass_kg=state.mass_kg
        + (dt_s / 6) * (k1.mass_kg + 2 * k2.mass_kg + 2 * k3.mass_kg + k4.mass_kg),
    )
