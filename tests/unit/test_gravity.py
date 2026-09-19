import math

from luminary_agent.plant.gravity import g


def test_surface_gravity_matches_commonly_cited_value() -> None:
    assert math.isclose(g(0.0), 1.62, rel_tol=0.01)


def test_gravity_decreases_with_altitude() -> None:
    assert g(100_000.0) < g(0.0)


def test_gravity_is_positive_everywhere_reasonable() -> None:
    for h in (0.0, 1_000.0, 15_000.0, 100_000.0):
        assert g(h) > 0.0
