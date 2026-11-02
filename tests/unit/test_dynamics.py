"""Analytic constant-acceleration checks, per CODE_REVIEW.md Phase 1's instruction
to validate the plant against closed-form cases before it's ever wired to the AGC.

Tests plant/dynamics.py and plant/gravity.py against physics with known answers.

Run alone: `uv run pytest tests/unit/test_dynamics.py -v`.
"""

import math

from luminary_agent.plant.dynamics import Control, PlanarState, derivative, step
from luminary_agent.plant.gravity import MU_MOON, R_MOON, g
from luminary_agent.plant.propulsion import DescentEngine

ENGINE = DescentEngine()


def _state(
    h: float = 1000.0,
    x: float = 0.0,
    hdot: float = 0.0,
    xdot: float = 0.0,
    mass: float = 15_000.0,
) -> PlanarState:
    return PlanarState(h_m=h, x_m=x, hdot_ms=hdot, xdot_ms=xdot, mass_kg=mass)


def test_free_fall_derivative_is_pure_gravity() -> None:
    s = _state()
    d = derivative(s, Control(throttle=0.0, pitch_rad=0.0), ENGINE)
    assert d.hdot_ms == -g(s.h_m)  # at rest tangentially there is no centrifugal term
    assert d.xdot_ms == 0.0
    assert d.mass_kg == 0.0  # no propellant burned with the engine off


def test_free_fall_integrates_to_kinematic_trajectory() -> None:
    s = _state(h=1000.0, hdot=0.0)
    dt = 0.02
    for _ in range(50):  # 1 second of fall
        s = step(s, Control(throttle=0.0, pitch_rad=0.0), ENGINE, dt)
    g0 = g(1000.0)
    assert math.isclose(s.hdot_ms, -g0 * 1.0, rel_tol=1e-3)
    assert math.isclose(s.h_m, 1000.0 - 0.5 * g0 * 1.0**2, rel_tol=1e-3)


def test_hovering_thrust_exactly_cancels_weight() -> None:
    s = _state(h=500.0, mass=10_000.0)
    weight = s.mass_kg * g(s.h_m)
    throttle = weight / ENGINE.f_max_n
    d = derivative(s, Control(throttle=throttle, pitch_rad=0.0), ENGINE)
    assert math.isclose(d.hdot_ms, 0.0, abs_tol=1e-9)


def test_full_horizontal_pitch_only_decelerates_downrange_velocity() -> None:
    s = _state(h=500.0, xdot=50.0, mass=10_000.0)
    d = derivative(s, Control(throttle=0.925, pitch_rad=math.pi / 2), ENGINE)
    centrifugal = s.xdot_ms**2 / (R_MOON + s.h_m)
    assert math.isclose(d.hdot_ms, centrifugal - g(s.h_m), rel_tol=1e-9)
    assert d.xdot_ms < 0.0  # thrust opposes downrange velocity


def test_mass_decreases_monotonically_while_firing() -> None:
    s = _state(mass=15_000.0)
    control = Control(throttle=0.5, pitch_rad=0.0)
    for _ in range(10):
        next_s = step(s, control, ENGINE)
        assert next_s.mass_kg < s.mass_kg
        s = next_s


def test_zero_throttle_conserves_mass_over_many_steps() -> None:
    s = _state(mass=15_000.0)
    control = Control(throttle=0.0, pitch_rad=0.0)
    for _ in range(100):
        s = step(s, control, ENGINE)
    assert s.mass_kg == 15_000.0


def test_circular_orbit_stays_circular() -> None:
    """The check a flat-Moon model fails: at circular speed sqrt(mu/r), centrifugal relief
    exactly cancels gravity, so altitude must hold and downrange must advance at v * R/r.
    """
    h = 15_000.0
    r = R_MOON + h
    v_circ = math.sqrt(MU_MOON / r)
    s = _state(h=h, xdot=v_circ)
    control = Control(throttle=0.0, pitch_rad=0.0)
    for _ in range(50 * 60):  # 60 s
        s = step(s, control, ENGINE)
    assert math.isclose(s.h_m, h, abs_tol=0.5)
    assert math.isclose(s.xdot_ms, v_circ, rel_tol=1e-6)
    assert math.isclose(s.x_m, v_circ * (R_MOON / r) * 60.0, rel_tol=1e-6)


def test_flat_moon_would_have_failed_the_orbit_check() -> None:
    """Documents why the polar form exists: at PDI speed the vertical acceleration is
    ~zero, not -g. Without the v^2/r term this would read ~ -1.6 m/s^2.
    """
    h = 15_000.0
    v_pdi = math.sqrt(MU_MOON / (R_MOON + h))
    d = derivative(_state(h=h, xdot=v_pdi), Control(0.0, 0.0), ENGINE)
    assert abs(d.hdot_ms) < 1e-6
