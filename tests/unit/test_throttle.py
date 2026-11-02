"""Unit tests for plant/throttle.py:ThrottleActuator (engine on/off, slew rate limit, clamping
at the minimum and the upper detent). `_on()` returns an actuator with the engine lit.

Run alone: `uv run pytest tests/unit/test_throttle.py -v`.
"""

import math

from luminary_agent.plant.propulsion import F_MAX_N, THRUST_N_PER_COUNT
from luminary_agent.plant.throttle import (
    MAX_COUNTS,
    MIN_COUNTS,
    SLEW_COUNTS_PER_S,
    ThrottleActuator,
)


def _on() -> ThrottleActuator:
    t = ThrottleActuator()
    t.set_engine(True)
    return t


def test_engine_off_produces_no_thrust_and_ignores_commands() -> None:
    t = ThrottleActuator()
    t.command(1000)
    t.step(1.0)
    assert t.thrust_n == 0.0


def test_ignition_starts_at_minimum_throttle() -> None:
    t = _on()
    assert math.isclose(t.throttle_fraction, 0.10)
    assert math.isclose(t.counts, MIN_COUNTS)


def test_increment_slews_at_32_counts_per_centisecond() -> None:
    t = _on()
    t.command(1000)
    t.step(0.10)  # 0.1 s -> at most 320 counts
    assert math.isclose(t.counts, MIN_COUNTS + 320.0)
    assert math.isclose(t.pending, 1000 - 320.0)


def test_small_increment_is_applied_fully_in_one_step() -> None:
    t = _on()
    t.command(50)
    t.step(0.02)  # 64-count budget
    assert math.isclose(t.counts, MIN_COUNTS + 50)
    assert t.pending == 0.0


def test_flatout_reaches_the_upper_stop_in_about_a_second_and_holds() -> None:
    t = _on()
    t.command(4096)  # FLATOUT: BIT13 pulses, more than the range
    elapsed = 0.0
    while t.counts < MAX_COUNTS and elapsed < 5.0:
        t.step(0.02)
        elapsed += 0.02
    assert math.isclose(t.counts, MAX_COUNTS)
    assert 0.8 < elapsed < 1.2  # (3467 - 375) counts at 3200/s
    assert t.pending == 0.0  # the excess command is discarded, not wound up
    t.step(1.0)
    assert math.isclose(t.counts, MAX_COUNTS)


def test_upper_stop_is_the_92_5_percent_detent() -> None:
    t = _on()
    t.command(4096)
    for _ in range(100):
        t.step(0.02)
    assert math.isclose(t.throttle_fraction, 0.925, abs_tol=1e-9)


def test_decrement_slews_down_and_clamps_at_minimum() -> None:
    t = _on()
    t.command(1500)
    for _ in range(100):
        t.step(0.02)
    high = t.counts
    t.command(-5000)
    for _ in range(200):
        t.step(0.02)
    assert high > MIN_COUNTS
    assert math.isclose(t.counts, MIN_COUNTS)


def test_engine_off_zeroes_thrust_and_discards_pending() -> None:
    t = _on()
    t.command(2000)
    t.step(0.1)
    t.set_engine(False)
    assert t.thrust_n == 0.0 and t.pending == 0.0
    t.set_engine(True)
    assert math.isclose(t.counts, MIN_COUNTS)  # a re-start begins at minimum, not where it left


def test_thrust_uses_the_source_derived_newtons_per_count() -> None:
    t = _on()
    assert math.isclose(t.thrust_n, MIN_COUNTS * THRUST_N_PER_COUNT)
    assert math.isclose(t.thrust_n, 0.10 * F_MAX_N)
    assert SLEW_COUNTS_PER_S == 3200
