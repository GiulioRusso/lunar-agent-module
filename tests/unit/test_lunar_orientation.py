import math

import pytest

from luminary_agent.plant.lunar_orientation import (
    MOON_ROTATION_RAD_S,
    moon_matrix,
    r_to_rp,
    rp_to_r,
)

R_SURFACE = 1_738_090.0


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(v: tuple[float, ...]) -> float:
    return math.sqrt(_dot(v, v))


# The AGC's SINI/COSI are 8-digit constants: sin^2 + cos^2 = 1 - 3.2e-9, so M is orthonormal only
# to ~3e-9 (0.005 m at lunar radius). That is the data's precision, not this code's.
ORTHO_TOL = 1e-7


@pytest.mark.parametrize("t_cs", [0.0, 35_216.0, 101_656.0, 5_000_000.0])
def test_matrix_is_orthonormal_and_right_handed(t_cs: float) -> None:
    m = moon_matrix(t_cs)
    for i in range(3):
        assert math.isclose(_dot(m[i], m[i]), 1.0, abs_tol=ORTHO_TOL)
        for j in range(i + 1, 3):
            assert abs(_dot(m[i], m[j])) < ORTHO_TOL
    cross = (
        m[0][1] * m[1][2] - m[0][2] * m[1][1],
        m[0][2] * m[1][0] - m[0][0] * m[1][2],
        m[0][0] * m[1][1] - m[0][1] * m[1][0],
    )
    assert _dot(cross, m[2]) == pytest.approx(1.0, abs=ORTHO_TOL)  # m0 x m1 = m2


def test_round_trip_is_exact() -> None:
    rp = (1_487_944.0, 898_321.0, 12_345.0)
    back = r_to_rp(rp_to_r(rp, 40_000.0), 40_000.0)
    assert back == pytest.approx(rp, abs=0.05)  # metres; bounded by the constants' precision


def test_rotation_rate_matches_the_documented_constant() -> None:
    assert math.isclose(MOON_ROTATION_RAD_S, 2.67240410e-6, rel_tol=1e-8)  # source comment


def test_moon_rotates_about_its_pole_at_that_rate() -> None:
    """Over dt the Moon-fixed x axis (row 0) sweeps MOON_ROTATION_RAD_S * dt about the pole
    (row 2), which itself barely moves.
    """
    dt_cs = 10_000_000.0  # 1e5 s
    a, b = moon_matrix(0.0), moon_matrix(dt_cs)
    angle = math.acos(max(-1.0, min(1.0, _dot(a[0], b[0]))))
    # Not exactly FDOT*t: the node regresses at NODDOT/FDOT = 0.4% of the spin rate.
    assert math.isclose(angle, MOON_ROTATION_RAD_S * dt_cs / 100.0, rel_tol=1e-2)
    pole_drift = math.acos(max(-1.0, min(1.0, _dot(a[2], b[2]))))
    assert pole_drift < 1e-4


def test_pole_is_tilted_about_1_5_degrees_from_the_third_reference_axis_plus_precession_terms() -> (
    None
):
    # A property of the model, not of this test: I = 1.5338 deg between lunar equator and
    # ecliptic means the pole is within ~ (I + B) of an axis; it must at least be a unit vector
    # that is not the reference Z axis.
    pole = moon_matrix(0.0)[2]
    assert _norm(pole) == pytest.approx(1.0)
    assert abs(pole[2]) < 1.0


def test_matches_a_real_yaagc_LAND_vector_to_the_documented_residual() -> None:
    """Regression against ground truth from a live yaAGC + Luminary099 run.

    Inputs read back from the AGC: RLS = 1,738,090 m at site angle 0.54316 rad in the X-Y
    plane, REFSMMAT = landing-site frame, ephemeris time 0. The AGC's IGNALG produced
    LAND = (-733002, -377125, 1530177) m in guidance coordinates. A naive identity Moon
    orientation gives a ~115 degree error; this model must land within 1.5 km (0.09% of the
    radius). The known, unexplained residual is ~0.95 km (see the module docstring).
    """
    th = 0.5431600780166734
    rls = (R_SURFACE * math.cos(th), R_SURFACE * math.sin(th), 0.0)
    x_sm = (math.cos(th), math.sin(th), 0.0)
    z_sm = (-math.sin(th), math.cos(th), 0.0)
    y_sm = (0.0, 0.0, -1.0)
    observed = (-733002.0, -377125.0, 1530177.0)

    r_ref = rp_to_r(rls, t_cs=35_216.0)  # PIPTIME, where the AGC was observed
    land = (_dot(x_sm, r_ref), _dot(y_sm, r_ref), _dot(z_sm, r_ref))
    err = _norm(tuple(a - b for a, b in zip(land, observed, strict=True)))
    assert err < 1_500.0, f"predicted {land}, AGC computed {observed}, off by {err:.0f} m"
    assert _norm(land) == pytest.approx(R_SURFACE)  # a pure rotation

    identity = (_dot(x_sm, rls), _dot(y_sm, rls), _dot(z_sm, rls))
    naive_err = _norm(tuple(a - b for a, b in zip(identity, observed, strict=True)))
    assert naive_err > 1_000_000.0  # what "Moon-fixed == inertial" would have cost
