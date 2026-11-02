"""The native window: live during a descent, or a replay of a recorded log. pygame-ce, no browser,
no server, no network.

Two modes share one renderer and one event loop:

  * `run_replay(episode)`  scrubbable playback of a recorded log;
  * `run_live(feed)`       frames arrive from a running simulation (viz/live.py); when it ends the
                           window switches to a replay of the recorded log, at full resolution.

The window never touches the simulation's clock: pausing here pauses the *view* (frames keep being
collected), and closing it does not stop the episode.

Keys: SPACE pause, LEFT/RIGHT scrub 5 s (SHIFT: 30 s), UP/DOWN speed, HOME/END start/end,
1/2/3 camera, ESC or Q quit.
pygame basics: every frame, read input events, update state, draw on `screen`, then
`pygame.display.flip()` to show it; `clock.tick(FPS)` waits so the loop runs ~30 times a second.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pygame

from luminary_agent.plant.terrain import Surface
from luminary_agent.viz.live import LiveReader
from luminary_agent.viz.native_renderer import CAMERAS, SIZE, NativeRenderer
from luminary_agent.viz.replay import Episode, load_episode
from luminary_agent.viz.view_model import ViewFrame

FPS = 30  # window refresh rate
SPEEDS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)  # replay speeds (x simulated time)
SCRUB_S = 5.0  # seconds jumped by one arrow-key press


def verdict_text(
    landing: Mapping[str, object] | None, summary: Mapping[str, object] | None = None
) -> str | None:
    """One line for the end of an episode, from the landing record or the run's summary."""
    score = (landing or {}).get("score") or summary
    if not isinstance(score, Mapping):
        return None
    if not score.get("landed"):
        return "NO LANDING"
    if not score.get("soft_touchdown"):
        return "LANDED, OUTSIDE LIMITS"
    mission = score.get("mission_success")
    tail = {
        "True": "MISSION SUCCESS",
        "False": "NOT MISSION SUCCESS",
        "not_scored": "MISSION NOT SCORED",
    }
    return f"SOFT TOUCHDOWN - {tail.get(str(mission), '?')}"


class Player:
    """Playback state, separate from pygame so it can be tested: a position in simulated time,
    a speed and a pause flag. `live` pins the position to the newest frame."""

    def __init__(self, frames: list[ViewFrame], live: bool = False) -> None:
        self.frames = frames
        self.live = live
        self.t_s = frames[0].t_s if frames else 0.0
        self.speed = 5.0
        self.paused = False

    def advance(self, wall_dt: float) -> None:
        """Move the playback position by wall_dt * speed (clamped at the last frame)."""
        if self.live or self.paused or not self.frames:
            return
        self.t_s = min(self.t_s + wall_dt * self.speed, self.frames[-1].t_s)

    def scrub(self, delta_s: float) -> None:
        """Jump by delta_s (leaves live mode)."""
        self.live = False
        if self.frames:
            self.t_s = min(max(self.t_s + delta_s, self.frames[0].t_s), self.frames[-1].t_s)

    def step_decision(self, direction: int) -> None:
        if not self.frames:
            return
        current = self.frames[self.index].decision_t_s
        anchor = current if current is not None else self.frames[self.index].t_s
        times = sorted({f.decision_t_s for f in self.frames if f.decision_t_s is not None})
        candidates = [t for t in times if (t - anchor) * direction > 1e-6]
        self.live, self.paused = False, True
        if candidates:
            self.t_s = min(candidates) if direction > 0 else max(candidates)

    def faster(self, direction: int) -> None:
        """Next (+1) or previous (-1) speed in SPEEDS."""
        i = SPEEDS.index(self.speed) if self.speed in SPEEDS else 1
        self.speed = SPEEDS[min(max(i + direction, 0), len(SPEEDS) - 1)]

    @property
    def index(self) -> int:
        """Index of the frame to draw (binary search on frame time)."""
        if not self.frames:
            return 0
        if self.live:
            return len(self.frames) - 1
        lo, hi = 0, len(self.frames) - 1
        while lo < hi:  # last frame at or before t_s
            mid = (lo + hi + 1) // 2
            if self.frames[mid].t_s <= self.t_s:
                lo = mid
            else:
                hi = mid - 1
        return lo


def _open_window(title: str, headless: bool) -> pygame.Surface:
    """Create the window. headless: SDL's "dummy" video driver, i.e. draw off-screen (tests,
    screenshots, machines without a display)."""
    if headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    pygame.display.set_caption(f"LUMINARY  {title}")
    return pygame.display.set_mode(SIZE)


def _loop(
    screen: pygame.Surface, renderer: NativeRenderer, player: Player,
    tick: Callable[[Player], bool] | None = None, verdict: Callable[[], str | None] = lambda: None,
    label: Callable[[Player], str] = lambda p: "",
) -> None:  # fmt: skip
    """The event loop. `tick` runs once per frame and returns True to leave the loop."""
    clock = pygame.time.Clock()
    camera = 1
    inspect = False
    while True:
        dt = clock.tick(FPS) / 1000.0  # wall seconds since the previous frame
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                return
            if event.type != pygame.KEYDOWN:
                continue
            big = 6 if event.mod & pygame.KMOD_SHIFT else 1  # SHIFT = 6x bigger jumps
            if event.key == pygame.K_SPACE:
                player.paused = not player.paused
                player.live = player.live and not player.paused
            elif event.key == pygame.K_i:
                inspect = not inspect
            elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
                player.step_decision(-1 if event.key == pygame.K_LEFTBRACKET else 1)
            elif event.key == pygame.K_LEFT:
                player.scrub(-SCRUB_S * big)
            elif event.key == pygame.K_RIGHT:
                player.scrub(SCRUB_S * big)
            elif event.key == pygame.K_UP:
                player.faster(1)
            elif event.key == pygame.K_DOWN:
                player.faster(-1)
            elif event.key == pygame.K_HOME:
                player.scrub(-1e9)
            elif event.key == pygame.K_END:
                player.scrub(1e9)
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                camera = event.key - pygame.K_0  # key "1" -> 1, etc.
        if tick is not None and tick(player):
            return
        player.advance(dt)
        renderer.draw(screen, player.frames, player.index, camera, label(player), verdict())
        if inspect and player.frames:
            renderer.draw_inspector(screen, player.frames[player.index])
        pygame.display.flip()


def run_replay(episode: Episode, headless: bool = False) -> None:
    """Open a window and play a recorded episode (`luminary view`). Returns when closed."""
    screen = _open_window(episode.title, headless)
    renderer = NativeRenderer(episode.surface)
    player = Player(episode.frames)
    end = verdict_text(episode.landing)

    def label(p: Player) -> str:
        state = "PAUSED" if p.paused else f"{p.speed:g}x"
        return f"REPLAY  {state}   {episode.title}"

    _loop(
        screen,
        renderer,
        player,
        verdict=lambda: end if player.index == len(player.frames) - 1 else None,
        label=label,
    )
    pygame.quit()


@dataclass
class LiveState:
    """Mutable flags shared by run_live's inner functions."""

    replay: bool = False  # the run ended and the window now shows its log
    verdict: str | None = None


def run_live(
    reader: LiveReader, log: Path, surface: Surface | None = None, headless: bool = False
) -> None:
    """Show frames as the simulation process publishes them. When the run ends and its log is
    written, continue as a replay of the log, at full resolution."""
    screen = _open_window(reader.title, headless)
    renderer = NativeRenderer(surface)
    player = Player([], live=True)
    state = LiveState()

    # Called once per window frame: pull new frames; on "end", swap to the full-resolution log.
    def tick(p: Player) -> bool:
        if state.replay:
            return False
        p.frames.extend(reader.poll())
        if reader.summary is not None:
            try:
                episode = load_episode(log)
            except (OSError, ValueError):  # the run failed before it wrote a log
                state.replay = True
                return False
            state.verdict = verdict_text(episode.landing, reader.summary)
            p.frames, p.live, p.paused = episode.frames, False, True
            p.t_s = episode.frames[-1].t_s if episode.frames else 0.0
            state.replay = True
        return False

    def label(p: Player) -> str:
        if state.replay:
            return f"DONE - replay  {'PAUSED' if p.paused else f'{p.speed:g}x'}  (esc closes)"
        return "LIVE" + ("  (view paused)" if p.paused else "")

    _loop(screen, renderer, player, tick=tick, verdict=lambda: state.verdict, label=label)
    pygame.quit()


def screenshot(
    episode: Episode, t_s: float, out: Path, camera: int = 1, inspect: bool = False
) -> None:
    """Render one frame of a recorded episode to a PNG, with no visible window."""
    _open_window(episode.title, headless=True)
    screen = pygame.display.get_surface()
    assert screen is not None and camera in CAMERAS
    renderer = NativeRenderer(episode.surface)
    index = episode.index_at(t_s)
    last = index == len(episode.frames) - 1
    renderer.draw(
        screen,
        episode.frames,
        index,
        camera,
        "SNAPSHOT",
        verdict_text(episode.landing) if last else None,
    )
    if inspect and episode.frames:
        renderer.draw_inspector(screen, episode.frames[index])
    pygame.image.save(screen, str(out))
    pygame.quit()
