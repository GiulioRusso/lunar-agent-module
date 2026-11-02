"""The safety monitor vetoes what it must and stays quiet through a nominal descent.

Reuses `obs()` from test_events.py (same folder) to build Observations.

Run alone: `uv run pytest tests/unit/test_safety.py -v`.
"""

from __future__ import annotations

from test_events import obs  # same directory; pytest puts it on sys.path

from luminary_agent.safety.monitor import REPEAT_S, SafetyMonitor, max_descent_rate_ms


def test_envelope_is_the_arrestable_descent_rate() -> None:
    assert max_descent_rate_ms(0.0) == 2.5  # contact at 1 m/s is a good landing, not a violation
    assert 4.0 < max_descent_rate_ms(10.0) < 5.0
    assert 60.0 < max_descent_rate_ms(2000.0) < 65.0  # a nominal braking phase fits inside


def test_a_nominal_profile_raises_no_veto() -> None:
    m = SafetyMonitor()
    profile = [(2000.0, -45.0, 150.0), (500.0, -25.0, 40.0), (100.0, -8.0, 5.0),
               (20.0, -2.0, 0.6), (2.0, -0.8, 0.1)]  # fmt: skip
    for i, (h, vz, vh) in enumerate(profile):
        assert m.check(obs(i * 10.0, radar_altitude_m=h, vertical_ms=vz, horizontal_ms=vh)) is None
    assert m.vetoes == []


def test_too_fast_for_the_altitude_takes_control_then_commands_a_safe_rate() -> None:
    m = SafetyMonitor()
    falling = dict(radar_altitude_m=50.0, vertical_ms=-25.0, horizontal_ms=0.0)
    v = m.check(obs(100.0, **falling))
    assert v is not None and v.intent.kind == "take_manual" and "exceeds" in v.reason
    # still outside the envelope, and now manual: the monitor commands a safe rate, but only
    # after REPEAT_S -- a standing violation is one decision, not fifty a second.
    assert m.check(obs(100.1, mode="manual", **falling)) is None
    v = m.check(obs(100.0 + REPEAT_S, mode="manual", **falling))
    assert v is not None and v.intent.kind == "command"
    assert v.intent.params["descent_rate_ms"] < 0.0
    assert len(m.vetoes) == 2


def test_a_standing_violation_does_not_spam_while_its_numbers_move() -> None:
    """The message carries live numbers, so de-duplication has to key on the rule. Keying on the
    message produced 381 vetoes in one real episode."""
    m = SafetyMonitor()
    for i in range(50):  # 5 s of ticks, the descent rate easing off every tick
        m.check(obs(100.0 + i * 0.1, mode="manual", radar_altitude_m=50.0 - i * 0.1,
                    vertical_ms=-25.0 + i * 0.05, horizontal_ms=0.0))  # fmt: skip
    assert len(m.vetoes) == 1


def test_the_monitor_hands_control_back_when_the_envelope_is_restored() -> None:
    m = SafetyMonitor()
    m.check(obs(100.0, mode="manual", radar_altitude_m=50.0, vertical_ms=-25.0))
    assert m.vetoes and m.vetoes[-1].intent.params["descent_rate_ms"] < 0.0
    v = m.check(obs(110.0, mode="manual", radar_altitude_m=40.0, vertical_ms=-2.0))
    assert v is not None and v.release and v.intent.params["descent_rate_ms"] is None
    assert len(m.vetoes) == 1  # a release is not a veto
    assert m.check(obs(111.0, mode="manual", radar_altitude_m=39.0, vertical_ms=-2.0)) is None


def test_horizontal_speed_near_the_ground_is_vetoed() -> None:
    m = SafetyMonitor()
    v = m.check(obs(300.0, mode="manual", radar_altitude_m=15.0, vertical_ms=-1.0,
                    horizontal_ms=6.0))  # fmt: skip
    assert v is not None and "horizontal" in v.reason and v.intent.kind == "command"


def test_a_noisy_altitude_around_the_threshold_does_not_flap_the_veto() -> None:
    """Radar noise around 30 m once produced veto/release three times a second."""
    m = SafetyMonitor()
    events = 0
    for i in range(60):
        h = 30.0 + (1.5 if i % 2 else -1.5)  # noise straddling the near-ground threshold
        v = m.check(obs(200.0 + i * 0.1, mode="manual", radar_altitude_m=h, vertical_ms=-1.0,
                        horizontal_ms=20.0))  # fmt: skip
        events += v is not None
    assert events == 2  # the veto, then one repeat after REPEAT_S -- no release in between


def test_without_an_altitude_the_monitor_does_not_guess() -> None:
    m = SafetyMonitor()
    blind = obs(50.0, radar_altitude_m=None, agc_altitude_m=None, vertical_ms=-80.0)
    assert m.check(blind) is None and m.vetoes == []
