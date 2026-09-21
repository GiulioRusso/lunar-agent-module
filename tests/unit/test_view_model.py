from viz_records import decision, tick

from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.propulsion import F_MAX_N
from luminary_agent.plant.surface import MOON_RATE_RAD_S
from luminary_agent.viz.view_model import FrameBuilder


def test_tick_becomes_a_frame_relative_to_the_target() -> None:
    f = FrameBuilder(site_x_m=940.0, dry_mass_kg=6_800.0).tick(tick())
    assert f.downrange_m == 60.0 and f.cross_m == 30.0
    assert abs(f.target_error_m - (60.0**2 + 30.0**2) ** 0.5) < 1e-9
    assert f.fuel_kg == 700.0 and abs(f.throttle - 0.5) < 1e-9
    assert (f.prog, f.verb, f.noun, f.r1, f.r2, f.r3) == (64, 6, 64, 1, None, -3)
    assert abs(f.vh_ms - (4.6 - MOON_RATE_RAD_S * (R_MOON + 500.0))) < 1e-9  # relative to surface


def test_fuel_and_throttle_are_clamped() -> None:
    f = FrameBuilder(0.0, 8_000.0).tick(tick(thrust_n=10 * F_MAX_N))
    assert f.fuel_kg == 0.0 and f.throttle == 1.0


def test_decisions_feed_the_next_frames_and_are_counted() -> None:
    b = FrameBuilder(0.0, 6_800.0)
    assert b.tick(tick()).intent == "" and b.tick(tick()).decisions == 0
    b.decision(decision("command"))
    b.decision(decision("take_manual", veto=True))
    f = b.tick(tick())
    assert f.intent == "take_manual" and f.veto and f.reason == "heartbeat" and f.applied == "ok"
    assert f.decisions == 2 and f.vetoes == 1 and f.alarms == (1201,)
    assert f.radar_alt_m == 498.0 and f.agc_alt_m == 510.0
    b.decision(decision("command"))
    assert b.tick(tick()).intent == "command(descent_rate_ms=-1.0)"
    assert not b.tick(tick()).veto  # the veto flag describes the latest decision only
