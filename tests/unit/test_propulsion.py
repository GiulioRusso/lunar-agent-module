"""Unit tests for plant/propulsion.py: the DPS throttle law (off / clamp-up / variable / detent)
and thrust -> mass flow.

Run alone: `uv run pytest tests/unit/test_propulsion.py -v`.
"""

import math

import pytest

from luminary_agent.plant.propulsion import (
    G0,
    THROTTLE_FIXED_DETENT,
    THROTTLE_MIN,
    DescentEngine,
    resolve_throttle,
)


def test_zero_commanded_throttle_is_engine_off() -> None:
    assert resolve_throttle(0.0) == 0.0


@pytest.mark.parametrize("commanded", [0.01, 0.05, 0.099])
def test_below_minimum_clamps_up_to_minimum(commanded: float) -> None:
    assert resolve_throttle(commanded) == THROTTLE_MIN


@pytest.mark.parametrize("commanded", [0.10, 0.35, 0.60])
def test_within_variable_range_is_held_as_commanded(commanded: float) -> None:
    assert resolve_throttle(commanded) == commanded


@pytest.mark.parametrize("commanded", [0.61, 0.80, 0.925, 1.0])
def test_above_variable_range_snaps_to_fixed_detent(commanded: float) -> None:
    assert resolve_throttle(commanded) == THROTTLE_FIXED_DETENT


def test_thrust_and_mdot_off() -> None:
    engine = DescentEngine()
    thrust, mdot = engine.thrust_and_mdot(0.0)
    assert thrust == 0.0
    assert mdot == 0.0


def test_thrust_and_mdot_scale_with_throttle() -> None:
    engine = DescentEngine()
    half_thrust, half_mdot = engine.thrust_and_mdot(0.30)
    assert math.isclose(half_thrust, 0.30 * engine.f_max_n)
    assert math.isclose(half_mdot, half_thrust / (G0 * engine.isp_s))


def test_mdot_is_positive_propellant_consumption() -> None:
    engine = DescentEngine()
    _, mdot = engine.thrust_and_mdot(0.925)
    assert mdot > 0.0
