import math

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.sim.frames import inertial_state_vector, inertial_vector


def test_at_t0_vertical_is_x_and_travel_is_y() -> None:
    assert inertial_vector(1.0, 0.0, 0.0) == (1.0, 0.0, 0.0)
    assert inertial_vector(0.0, 1.0, 0.0) == (0.0, 1.0, 0.0)


def test_after_a_quarter_orbit_vertical_has_rotated_to_y() -> None:
    x, y, z = inertial_vector(1.0, 0.0, math.pi / 2)
    assert (round(x, 12), round(y, 12), z) == (0.0, 1.0, 0.0)


def test_circular_orbit_state_vector_is_perpendicular_and_has_the_right_speed() -> None:
    h = 15_000.0
    r = R_MOON + h
    v = math.sqrt(MU_MOON / r)
    sv = inertial_state_vector(PlanarState(h, 0.0, 0.0, v, 15_000.0), t_cs=0.0)
    assert sv.r_m == (r, 0.0, 0.0)
    assert sv.v_ms == (0.0, v, 0.0)
    assert sum(a * b for a, b in zip(sv.r_m, sv.v_ms, strict=True)) == 0.0  # r . v = 0


def test_speed_and_radius_survive_the_rotation() -> None:
    s = PlanarState(15_000.0, 200_000.0, -5.0, 1_600.0, 15_000.0)
    sv = inertial_state_vector(s, 0.0)
    assert math.isclose(math.hypot(*sv.r_m), R_MOON + 15_000.0)
    assert math.isclose(math.hypot(*sv.v_ms), math.hypot(-5.0, 1_600.0))
