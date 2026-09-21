"""The native window, headless: SDL's dummy video driver, no display needed."""

from pathlib import Path

import pygame
from viz_records import decision, tick

from luminary_agent.plant.terrain import Surface
from luminary_agent.viz import native_app
from luminary_agent.viz.native_app import Player, verdict_text
from luminary_agent.viz.native_renderer import SIZE, NativeRenderer
from luminary_agent.viz.replay import Episode
from luminary_agent.viz.view_model import FrameBuilder, ViewFrame


def frames(n: int = 40, pitch: float = 20.0) -> list[ViewFrame]:
    b = FrameBuilder(0.0, 6_800.0)
    b.decision(decision("command"))
    return [
        b.tick(tick(t=float(i), h_m=400.0 - 10 * i, x_m=-300.0 + 5 * i, pitch_deg=pitch))
        for i in range(n)
    ]


def lit(img: pygame.Surface, rect: pygame.Rect) -> int:
    """How many pixels of `rect` differ from its corner: a crude 'something was drawn there'."""
    sub = img.subsurface(rect)
    bg = sub.get_at((0, 0))
    return sum(sub.get_at((x, y)) != bg for x in range(0, rect.w, 3) for y in range(0, rect.h, 3))


def test_every_camera_draws_scene_plots_and_panel() -> None:
    renderer = NativeRenderer(Surface.sample(1))
    screen = pygame.Surface(SIZE)
    fs = frames()
    for camera in (1, 2, 3):
        renderer.draw(screen, fs, 30, camera)
        assert lit(screen, pygame.Rect(0, 0, 800, 470)) > 200  # the scene
        assert lit(screen, pygame.Rect(0, 470, 800, 250)) > 100  # profile and altitude strip
        assert lit(screen, pygame.Rect(800, 0, 480, 450)) > 300  # DSKY and telemetry


def test_the_lem_sprite_is_cached_by_pitch_and_view() -> None:
    renderer, screen = NativeRenderer(None), pygame.Surface(SIZE)
    fs = frames(pitch=20.0)
    renderer.draw(screen, fs, 39, 1)
    misses = renderer.sprite_misses
    renderer.draw(screen, fs, 39, 1)
    renderer.draw(screen, fs, 38, 1)  # same pitch, same camera direction: no new sprite
    assert misses >= 1 and renderer.sprite_misses == misses
    renderer.draw(screen, frames(pitch=60.0), 39, 1)
    assert renderer.sprite_misses == misses + 1  # a new pitch is a new sprite


def test_drawing_with_nothing_to_show_or_an_out_of_range_index_is_safe() -> None:
    renderer, screen = NativeRenderer(None), pygame.Surface(SIZE)
    renderer.draw(screen, [], 0)
    renderer.draw(screen, frames(3), 99, 2, "x", "SOFT TOUCHDOWN - MISSION SUCCESS")


def test_a_high_vehicle_is_a_marker_and_touchdown_fills_the_view() -> None:
    renderer, screen = NativeRenderer(None), pygame.Surface(SIZE)
    high = [FrameBuilder(0.0, 6_800.0).tick(tick(h_m=9_000.0, x_m=-5_000.0))]
    renderer.draw(screen, high, 0, 2)  # the fixed ground observer, ~10 km away
    assert renderer.sprite_misses == 0  # too far for a sprite
    renderer.draw(screen, high, 0, 1)  # the chase camera keeps it in view
    assert renderer.sprite_misses == 1
    low = [FrameBuilder(0.0, 6_800.0).tick(tick(h_m=2.0, x_m=0.0))]
    renderer.draw(screen, low, 0, 1)
    assert renderer.sprite_misses == 1  # drawn from the cached sprite, scaled up


def test_player_moves_in_simulated_time_and_respects_pause_and_scrub() -> None:
    p = Player(frames(40))
    assert p.index == 0
    p.speed = 2.0
    p.advance(1.0)
    assert p.t_s == 2.0 and p.index == 2
    p.paused = True
    p.advance(5.0)
    assert p.t_s == 2.0
    p.scrub(10.0)
    assert p.t_s == 12.0
    p.scrub(1e9)
    assert p.index == 39
    p.faster(1)
    p.faster(1)
    assert p.speed == 10.0 and Player(frames(2)).speed == 5.0
    p.scrub(-1e9)
    assert p.index == 0


def test_a_live_player_stays_on_the_newest_frame_until_scrubbed() -> None:
    p = Player([], live=True)
    assert p.index == 0
    p.frames.extend(frames(5))
    p.advance(10.0)
    assert p.index == 4
    p.scrub(-2.0)
    assert not p.live


def test_verdict_text_never_calls_a_far_soft_touchdown_a_mission_success() -> None:
    def score(**kw: object) -> dict[str, dict[str, object]]:
        return {"score": {"landed": True, "soft_touchdown": True, **kw}}

    assert verdict_text(score(mission_success=True)) == "SOFT TOUCHDOWN - MISSION SUCCESS"
    assert verdict_text(score(mission_success=False)) == "SOFT TOUCHDOWN - NOT MISSION SUCCESS"
    assert verdict_text(score(mission_success="not_scored")) == (
        "SOFT TOUCHDOWN - MISSION NOT SCORED"
    )
    assert verdict_text({"score": {"landed": True, "soft_touchdown": False}}) == (
        "LANDED, OUTSIDE LIMITS"
    )
    assert verdict_text({"score": {"landed": False}}) == "NO LANDING"
    assert verdict_text(None) is None
    assert verdict_text(None, {"landed": True, "soft_touchdown": True, "mission_success": True})


def test_the_event_loop_closes_on_quit_and_on_escape() -> None:
    for event in (pygame.event.Event(pygame.QUIT),
                  pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)):  # fmt: skip
        screen = native_app._open_window("test", headless=True)
        pygame.event.post(event)
        native_app._loop(screen, NativeRenderer(None), Player(frames(3)))
        pygame.quit()


def test_screenshot_writes_a_png_without_opening_a_window(tmp_path: Path) -> None:
    landing = {"score": {"landed": True, "soft_touchdown": True, "mission_success": False}}
    episode = Episode({"policy": "null", "tier": 1, "seed": 0}, frames(20), landing)
    out = tmp_path / "shot.png"
    native_app.screenshot(episode, 10.0, out, camera=2)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and out.stat().st_size > 5_000
