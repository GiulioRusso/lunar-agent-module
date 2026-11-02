"""Unit tests for plant/terrain.py: seeded surfaces, the clear target, slope maths and the
hazard/slope/target verdict that mission_success is built on.

Run alone: `uv run pytest tests/unit/test_terrain.py -v`.
"""

import json
import math

from luminary_agent.plant.terrain import (
    CLEAR_RADIUS_M,
    FOOTPRINT_RADIUS_M,
    MAX_SLOPE_DEG,
    Bump,
    Hazard,
    Surface,
)


def test_sample_is_deterministic_and_seed_dependent() -> None:
    assert Surface.sample(3) == Surface.sample(3)
    assert Surface.sample(3) != Surface.sample(4)


def test_the_target_is_clear_flat_and_a_success_site() -> None:
    for seed in range(20):
        s = Surface.sample(seed)
        a = s.assess(0.0, 0.0)
        assert a.hazard_free and a.slope_ok and a.target_ok and a.slope_deg < 0.5
        assert all(math.hypot(h.x_m, h.z_m) > CLEAR_RADIUS_M for h in s.hazards)


def test_slope_of_a_gaussian_bump_matches_the_analytic_gradient() -> None:
    s = Surface(0, bumps=(Bump(0.0, 0.0, 20.0, 100.0),))
    x = 100.0  # one sigma out: dh/dx = -h/sigma * exp(-0.5)
    expected = math.degrees(math.atan(20.0 / 100.0 * math.exp(-0.5)))
    assert abs(s.slope_deg(x, 0.0, baseline_m=0.01) - expected) < 0.01
    assert abs(s.slope_deg(x, 0.0) - expected) < 0.1  # the 4.7 m footprint baseline barely smooths


def test_a_hazard_or_a_slope_changes_the_verdict() -> None:
    flat = Surface(0)
    assert flat.assess(50.0, 0.0).hazard_free
    boulder = Surface(0, hazards=(Hazard("boulder", 50.0, 0.0, 2.0),))
    a = boulder.assess(50.0 + 2.0 + FOOTPRINT_RADIUS_M - 0.1, 0.0)  # footpad overlaps it
    assert not a.hazard_free and a.hazard is not None
    assert boulder.assess(50.0 + 2.0 + FOOTPRINT_RADIUS_M + 0.1, 0.0).hazard_free
    steep = Surface(0, bumps=(Bump(0.0, 0.0, 40.0, 60.0),))
    assert steep.assess(60.0, 0.0).slope_deg > MAX_SLOPE_DEG
    assert not steep.assess(60.0, 0.0).slope_ok


def test_target_error_is_the_horizontal_distance() -> None:
    a = Surface(0).assess(60.0, 80.0)
    assert a.target_error_m == 100.0 and a.target_ok
    assert not Surface(0).assess(60.0, 81.0).target_ok


def test_a_surface_survives_the_log_round_trip() -> None:
    s = Surface.sample(5)
    assert Surface.from_dict(json.loads(json.dumps(s.as_dict()))) == s


def test_slope_map_is_the_vectorised_slope() -> None:
    s = Surface.sample(2)
    grid = s.slope_map(300.0, 50.0)
    axis = [-300.0 + 50.0 * i for i in range(13)]
    assert grid.shape == (13, 13)
    for j, z in enumerate(axis):
        for i, x in enumerate(axis):
            assert abs(grid[j, i] - s.slope_deg(x, z)) < 1e-9
