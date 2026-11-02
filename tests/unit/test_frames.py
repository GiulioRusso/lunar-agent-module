"""Unit tests for sim/frames.py: the 2-D plant plane placed in the AGC's 3-D reference frame,
the landing REFSMMAT, the Moon-fixed landing site (RLS), and state-vector construction.
`pytest.approx` compares floats with a tolerance.

Run alone: `uv run pytest tests/unit/test_frames.py -v`.
"""

import math

import pytest

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.plant.lunar_orientation import moon_matrix, rp_to_r
from luminary_agent.sim.frames import (
    PLANE_IS_XY,
    LunarFrame,
    cross,
    dot,
    inertial_vector,
    mat_vec,
)

FRAME = LunarFrame.from_moon(t_ref_cs=100_000.0)
T_LAND = 101_656.0
THETA = 0.5431600780166734


def _norm(v: tuple[float, ...]) -> float:
    return math.sqrt(dot(v, v))  # type: ignore[arg-type]


def test_plane_basis_is_orthonormal_and_the_normal_is_the_moons_pole() -> None:
    assert _norm(FRAME.e1) == pytest.approx(1.0, abs=1e-7)
    assert _norm(FRAME.e2) == pytest.approx(1.0, abs=1e-7)
    assert dot(FRAME.e1, FRAME.e2) == pytest.approx(0.0, abs=1e-7)
    pole = moon_matrix(100_000.0)[2]
    assert abs(dot(FRAME.normal, pole)) == pytest.approx(1.0, abs=1e-7)  # the equatorial plane


def test_the_moon_rotates_prograde_in_the_plant_plane() -> None:
    """The Moon-fixed x axis moves from e1 toward e2 -- the plant's +theta direction -- so a
    vehicle orbiting prograde moves with the Moon's spin.
    """
    later = moon_matrix(100_000.0 + 10_000.0)[0]
    assert dot(later, FRAME.e2) > 0.0


def test_in_plane_vector_rotation() -> None:
    assert inertial_vector(1.0, 0.0, 0.0) == (1.0, 0.0)
    x, y = inertial_vector(1.0, 0.0, math.pi / 2)
    assert (round(x, 12), round(y, 12)) == (0.0, 1.0)
    assert inertial_vector(0.0, 1.0, 0.0) == (0.0, 1.0)


def test_landing_refsmmat_is_right_handed_with_x_up_and_z_toward_travel() -> None:
    m = FRAME.landing_refsmmat(THETA)
    up, y, travel = m
    assert up == pytest.approx(FRAME.site_ref(THETA, 1.0), abs=1e-12)
    for i in range(3):
        assert _norm(m[i]) == pytest.approx(1.0, abs=1e-7)
    assert cross(up, y) == pytest.approx(travel, abs=1e-7)  # X x Y = Z
    # A vehicle uprange of the site is at negative Z in stable-member axes (RIGNZ < 0).
    uprange = FRAME.site_ref(THETA - 0.25, R_MOON)
    site = FRAME.site_ref(THETA, R_MOON)
    rel = tuple(a - b for a, b in zip(uprange, site, strict=True))
    assert mat_vec(m, rel)[2] < 0.0  # type: ignore[arg-type]


def test_rls_maps_back_to_the_site_at_tland() -> None:
    """R-TO-RP then RP-TO-R at the same time must return the reference-frame site, which is
    what makes Luminary's LAND land where we intend.
    """
    rls = FRAME.rls(THETA, T_LAND)
    assert rp_to_r(rls, T_LAND) == pytest.approx(FRAME.site_ref(THETA), abs=0.1)
    assert _norm(rls) == pytest.approx(R_MOON, abs=0.1)


def test_landing_geometry_in_guidance_axes_matches_the_pad_loaded_targets() -> None:
    """RIGNX = -40.9 km ("altitude") and RIGNZ = -440 km (ground range) from Luminary's pad
    loads must be what a vehicle at 15.4 km altitude and 440 km ground range reads in the
    landing-site frame -- the check that ties this frame to the flight software's targets.
    """
    m = FRAME.landing_refsmmat(THETA)
    theta_lm = THETA - 440_015.0 / R_MOON
    r_lm = FRAME.site_ref(theta_lm, R_MOON + 15_400.0)
    rgu = mat_vec(m, tuple(a - b for a, b in zip(r_lm, FRAME.site_ref(THETA, R_MOON), strict=True)))  # type: ignore[arg-type]
    assert rgu[0] == pytest.approx(-40_943.0, abs=1_500.0)  # RIGNX
    assert rgu[1] == pytest.approx(0.0, abs=1e-3)  # in-plane: no cross-range
    assert rgu[2] == pytest.approx(-440_015.0 * math.cos(0.0), abs=6_000.0)  # RIGNZ


def test_state_vector_of_a_circular_orbit_is_perpendicular_with_the_right_speed() -> None:
    h = 15_000.0
    v = math.sqrt(MU_MOON / (R_MOON + h))
    sv = FRAME.state_vector(PlanarState(h, 0.0, 0.0, v, 15_000.0), t_cs=0.0)
    assert _norm(sv.r_m) == pytest.approx(R_MOON + h)
    assert _norm(sv.v_ms) == pytest.approx(v)
    assert dot(sv.r_m, sv.v_ms) == pytest.approx(0.0, abs=1e-6)
    # And it lies in the plant plane: no component along the plane normal.
    assert dot(sv.r_m, FRAME.normal) == pytest.approx(0.0, abs=1e-6)


def test_xy_frame_is_the_identity_embedding() -> None:
    assert PLANE_IS_XY.to_ref(3.0, 4.0) == (3.0, 4.0, 0.0)
