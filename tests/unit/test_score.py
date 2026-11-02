"""Unit tests for eval/score.py: soft_touchdown vs mission_success, on hand-made DescentResults
(`_res`) and hand-made Surfaces (a flat one, one with a boulder, one with a steep bump).

Run alone: `uv run pytest tests/unit/test_score.py -v`.
"""

from luminary_agent.eval.score import score
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.terrain import Bump, Hazard, Surface
from luminary_agent.sim.descent import DescentResult


def _res(outcome: str, hdot: float, vt: float, x_m: float = 0.0, z_m: float = 0.0) -> DescentResult:
    return DescentResult(outcome, 1000.0, PlanarState(0.0, x_m, hdot, vt, 7500.0), lateral_m=z_m)


def test_soft_touchdown_is_not_mission_success_until_surface_is_scored() -> None:
    s = score(_res("touchdown", -0.8, 4.6))
    assert s.landed and s.soft_touchdown and s.fuel_kg == 700.0
    assert s.mission_success == "not_scored" and s.hazard_free is None


def test_hard_landing_and_no_landing() -> None:
    assert not score(_res("touchdown", -4.6, 4.6)).soft_touchdown
    assert not score(_res("time_limit", 0.0, 4.6)).landed


def test_mission_success_requires_target_hazard_and_slope() -> None:
    flat = Surface(0)
    far = score(_res("touchdown", -0.8, 4.6, x_m=802.0), surface=flat)
    assert far.soft_touchdown and far.mission_success is False and far.target_ok is False
    good = _res("touchdown", -0.8, 4.6, x_m=99.0)
    assert score(good, surface=flat).mission_success is True
    rock = Surface(0, hazards=(Hazard("boulder", 99.0, 0.0, 2.0),))
    hazard = score(good, surface=rock)
    assert hazard.mission_success is False and hazard.hazard == "boulder" and hazard.target_ok
    steep = Surface(0, bumps=(Bump(99.0, 60.0, 60.0, 40.0),))
    tilted = score(_res("touchdown", -0.8, 4.6, x_m=99.0, z_m=0.0), surface=steep)
    assert tilted.slope_ok is False and tilted.mission_success is False


def test_lateral_error_counts_and_a_hard_landing_is_never_mission_success() -> None:
    off = score(_res("touchdown", -0.8, 4.6, x_m=60.0, z_m=81.0), surface=Surface(0))
    assert off.target_error_m > 100.0 and off.mission_success is False
    hard = score(_res("touchdown", -4.6, 4.6, x_m=0.0), surface=Surface(0))
    assert hard.mission_success is False
