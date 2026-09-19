from luminary_agent.eval.score import score
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.sim.descent import DescentResult


def _res(outcome: str, hdot: float, vt: float) -> DescentResult:
    return DescentResult(outcome, 1000.0, PlanarState(0.0, 0.0, hdot, vt, 7500.0))


def test_safe_landing() -> None:
    s = score(_res("touchdown", -0.8, 4.6))
    assert s.landed and s.safe and s.fuel_kg == 700.0


def test_hard_landing_and_no_landing() -> None:
    assert not score(_res("touchdown", -4.6, 4.6)).safe
    assert not score(_res("time_limit", 0.0, 4.6)).landed
