"""Unit tests for plant/surface.py: speed relative to the rotating Moon and downrange error sign.

Run alone: `uv run pytest tests/unit/test_surface.py -v`.
"""

import math

import pytest

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.surface import (
    MOON_RATE_RAD_S,
    downrange_error_m,
    horizontal_speed_relative_to_surface,
)


def test_moon_rate_is_the_sidereal_rotation() -> None:
    assert math.isclose(MOON_RATE_RAD_S, 2.6617e-6, rel_tol=1e-3)  # 27.32-day period
    assert math.isclose(2 * math.pi / MOON_RATE_RAD_S / 86_400.0, 27.32, rel_tol=2e-3)


def test_a_vehicle_co_moving_with_the_surface_has_zero_relative_speed() -> None:
    surface_speed = MOON_RATE_RAD_S * R_MOON
    assert math.isclose(surface_speed, 4.626, rel_tol=1e-3)  # the ~4.6 m/s the plan warned of
    s = PlanarState(0.0, 0.0, 0.0, surface_speed, 8_000.0)
    assert horizontal_speed_relative_to_surface(s) == pytest.approx(0.0, abs=1e-9)


def test_an_inertially_stationary_vehicle_moves_backward_over_the_surface() -> None:
    s = PlanarState(0.0, 0.0, 0.0, 0.0, 8_000.0)
    assert horizontal_speed_relative_to_surface(s) < -4.0


def test_downrange_error_sign() -> None:
    site = 0.5
    long_ = PlanarState(0.0, site * R_MOON + 250.0, 0.0, 0.0, 1.0)
    short = PlanarState(0.0, site * R_MOON - 40.0, 0.0, 0.0, 1.0)
    assert downrange_error_m(long_, site) == pytest.approx(250.0, abs=1e-6)
    assert downrange_error_m(short, site) == pytest.approx(-40.0, abs=1e-6)
