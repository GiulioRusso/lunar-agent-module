"""Analytic constant-acceleration checks for the IMU model, per
CODE_REVIEW.md Phase 1's explicit instruction to validate this "most
failure-prone module" before it's ever wired to the AGC.

Tests plant/sensors.py (PIPA/CDU pulse scale factors and the PulseCounter quantiser).

Run alone: `uv run pytest tests/unit/test_sensors.py -v`.
"""

import math

from luminary_agent.plant.sensors import CDU_SCALE_RAD, PIPA_SCALE_MS, Imu, PulseCounter


def test_pipa_pulse_is_one_cm_per_second_as_luminary_scales_it() -> None:
    # KPIP1 = .0128 scales DELV (pulses * 2**-14) to units of 2**7 m/cs.
    from_kpip1_m_per_cs = 2.0**-14 * 0.0128 * 2.0**7
    assert math.isclose(PIPA_SCALE_MS, from_kpip1_m_per_cs * 100.0)  # m/cs -> m/s
    assert math.isclose(PIPA_SCALE_MS, 0.01)


def test_cdu_scale_factor_matches_15_bit_counter() -> None:
    # 360 degrees over a full 2^15-count revolution.
    assert math.isclose(math.degrees(CDU_SCALE_RAD), 360.0 / 32768.0)
    # Cross-check against the independently-known arcsecond value for the same constant.
    assert math.isclose(math.degrees(CDU_SCALE_RAD) * 3600.0, 39.55078125)


def test_zero_input_emits_no_pulses_and_no_drift() -> None:
    counter = PulseCounter(scale=1.0)
    for _ in range(1000):
        assert counter.pulses_for(0.0) == 0
    assert counter._residual == 0.0


def test_constant_acceleration_pulse_rate_matches_analytic_velocity() -> None:
    """A constant 1g-equivalent specific force integrated for 10s should produce a pulse
    count within one pulse of the exact analytic velocity change / scale factor -- the
    quantization error can never exceed one pulse, however the steps are chopped up.
    """
    a = 1.62  # m/s^2
    dt = 1.0 / 50.0
    steps = 500  # 10 seconds
    counter = PulseCounter(scale=PIPA_SCALE_MS)
    total_pulses = sum(counter.pulses_for(a * dt) for _ in range(steps))
    exact_pulses = a * (steps * dt) / PIPA_SCALE_MS
    assert abs(total_pulses - exact_pulses) < 1.0


def test_sub_threshold_acceleration_eventually_produces_a_pulse() -> None:
    """A sustained acceleration too small to cross the threshold in one step must still
    accumulate and eventually emit a pulse -- this is the whole point of tracking the
    fractional residual instead of truncating every step in isolation.
    """
    counter = PulseCounter(scale=1.0)
    tiny_delta = 0.01  # far below the scale, would round to 0 pulses if not accumulated
    pulses = [counter.pulses_for(tiny_delta) for _ in range(150)]
    assert sum(pulses) == 1
    assert pulses.count(1) == 1  # exactly one step emits the pulse, at the 100th call
    assert pulses.index(1) == 99


def test_negative_acceleration_emits_negative_pulses() -> None:
    counter = PulseCounter(scale=1.0)
    assert counter.pulses_for(-2.5) == -2
    assert math.isclose(counter._residual, -0.5)


def test_imu_samples_three_independent_axes() -> None:
    imu = Imu()
    (px, py, pz), cdu = imu.sample((10.0, 0.0, -10.0), pitch_rate_rad_s=0.0, dt_s=1.0)
    assert px > 0 and py == 0 and pz < 0
    assert cdu == 0
