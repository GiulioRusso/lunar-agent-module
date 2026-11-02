"""Unit tests for plant/orbit.py (Kepler ellipse): conservation laws, the perilune-speed solver,
and agreement with the RK4 plant integrating the same orbit.

Run alone: `uv run pytest tests/unit/test_orbit.py -v`.
"""

import math

import pytest

from luminary_agent.plant.dynamics import Control, step
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.orbit import DescentOrbit
from luminary_agent.plant.propulsion import DescentEngine

ORBIT = DescentOrbit(rp_m=R_MOON + 15_400.0, ra_m=R_MOON + 111_000.0)


def test_vis_viva_at_perilune_and_apolune() -> None:
    vp = ORBIT.perilune_speed_ms
    assert math.isclose(vp**2, MU_MOON * (2 / ORBIT.rp_m - 1 / ORBIT.a_m), rel_tol=1e-9)
    va = ORBIT.h_m2s / ORBIT.ra_m
    assert math.isclose(va**2, MU_MOON * (2 / ORBIT.ra_m - 1 / ORBIT.a_m), rel_tol=1e-9)


def test_energy_and_angular_momentum_are_constant_along_the_orbit() -> None:
    for nu in (-1.0, -0.3, 0.0, 0.7, 2.5):
        r = ORBIT.radius_at(nu)
        vr, vt = ORBIT.velocity_at(nu)
        assert math.isclose(
            0.5 * (vr**2 + vt**2) - MU_MOON / r, -MU_MOON / (2 * ORBIT.a_m), rel_tol=1e-9
        )
        assert math.isclose(r * vt, ORBIT.h_m2s, rel_tol=1e-9)


def test_descending_before_perilune_and_level_at_it() -> None:
    assert ORBIT.velocity_at(-0.3)[0] < 0.0
    assert ORBIT.velocity_at(0.0)[0] == pytest.approx(0.0, abs=1e-9)


def test_solver_hits_the_requested_perilune_speed() -> None:
    o = DescentOrbit.with_perilune_speed(15_400.0, 1_699.5)
    assert math.isclose(o.perilune_speed_ms, 1_699.5, rel_tol=1e-9)
    assert math.isclose(o.rp_m, R_MOON + 15_400.0)
    assert o.ra_m > o.rp_m


def test_escape_speed_is_rejected() -> None:
    with pytest.raises(ValueError, match="escape"):
        DescentOrbit.with_perilune_speed(15_400.0, 3_000.0)


def test_kepler_time_matches_numerical_integration_of_the_plant() -> None:
    """The check that ties this module to dynamics.py: start at true anomaly -0.29 rad and
    integrate the RK4 plant for the analytic time-to-perilune. It must arrive at perilune
    (radial velocity ~0, radius = rp), or one of the two models is wrong.
    """
    o = DescentOrbit.with_perilune_speed(15_400.0, 1_699.5)
    nu0 = -0.29
    tau = o.time_to_perilune_s(nu0)
    assert 250.0 < tau < 350.0  # ~5 minutes at ~1.7 km/s
    state = o.state_at(nu0, 15_000.0)
    engine, control = DescentEngine(), Control(0.0, 0.0)
    for _ in range(round(tau / 0.02)):
        state = step(state, control, engine)
    assert abs(state.hdot_ms) < 0.5
    assert math.isclose(state.h_m, o.rp_m - R_MOON, abs_tol=5.0)
    assert math.isclose(state.xdot_ms, o.perilune_speed_ms, rel_tol=1e-3)
