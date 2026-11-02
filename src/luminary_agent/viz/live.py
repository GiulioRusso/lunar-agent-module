"""The bridge from a running simulation to the window: a bounded, latest-wins frame feed.

The simulation and the window are **separate processes** (`luminary fly`): they share nothing but a
queue. That is deliberate. The simulation is a chain of tiny round trips to the emulator, so it is
latency-bound; a window drawing in the same process, even in another thread, holds the interpreter
lock in slices and made a descent run ~50x slower. In its own process the simulation runs at full
speed whatever the window does.

**The view is a window onto the simulation, never a part of it**: `LiveFeed.publish_*` never
blocks and never raises into the caller, and a window that falls behind loses the oldest frames,
not the newest. The recorded log is written the same whether or not a window is open.

The simulation ticks at 50 Hz of simulated time and runs ~20x faster than real time (~1,000 ticks a
wall second), so ticks are thinned to `PUBLISH_HZ` of wall clock before they become frames.
Decisions are never dropped from the *state* (they update every later frame).

Data flow:  simulation process  --LiveFeed.publish_*-->  multiprocessing.Queue  -->
            window process      --LiveReader.poll()--->  list of ViewFrames to draw.
Each queue item is a tuple: ("frame", ViewFrame) or ("end", score summary dict).
"""

from __future__ import annotations

import queue
import time
from typing import Any, Protocol

from luminary_agent.viz.view_model import FrameBuilder, ViewFrame

PUBLISH_HZ = 20.0  # at most 20 frames per wall second reach the window
BACKLOG = 2048  # frames held for a slow window before the oldest are dropped


class Channel(Protocol):
    """What `queue.Queue` and `multiprocessing.Queue` both offer."""

    def put_nowait(self, item: Any, /) -> None: ...
    def get_nowait(self) -> Any: ...


class LiveFeed:
    """The simulation side: turns records into frames and puts them on the channel."""

    def __init__(self, site_x_m: float, dry_mass_kg: float, channel: Channel) -> None:
        self._builder = FrameBuilder(site_x_m, dry_mass_kg)
        self._channel = channel
        self._last_s = float("-inf")
        self._last_tick: dict[str, Any] | None = None

    def _put(self, item: tuple[str, Any]) -> None:
        """Non-blocking put; if the queue is full, evict the oldest item first."""
        try:
            self._channel.put_nowait(item)
        except queue.Full:
            try:  # a window that cannot keep up loses the oldest frame, not the newest
                self._channel.get_nowait()
                self._channel.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass

    def publish_tick(self, record: dict[str, Any]) -> None:
        """Called every tick by the simulation; forwards at most PUBLISH_HZ frames per second."""
        self._last_tick = record
        now = time.monotonic()
        if now - self._last_s < 1.0 / PUBLISH_HZ:
            return
        self._last_s = now
        self._put(("frame", self._builder.tick(record)))

    def publish_decision(self, record: dict[str, Any]) -> None:
        """Publish a decision immediately, even when there will be no subsequent tick."""
        self._builder.decision(record)
        if self._last_tick is not None:
            self._put(("frame", self._builder.tick(self._last_tick)))

    def publish_agent_status(self, record: dict[str, Any]) -> None:
        self._builder.agent_status(record)
        if self._last_tick is not None:
            self._put(("frame", self._builder.tick(self._last_tick)))

    def publish_end(self, summary: dict[str, Any]) -> None:
        """Tell the window the run is over (with the score)."""
        self._put(("end", summary))


class LiveReader:
    """The window side: drains the channel."""

    def __init__(self, channel: Channel, title: str = "") -> None:
        self.title = title
        self._channel = channel
        self.summary: dict[str, Any] | None = None  # the final verdict, once the run has ended

    def poll(self) -> list[ViewFrame]:
        """Everything that arrived since the last call (never waits)."""
        frames: list[ViewFrame] = []
        while True:
            try:
                kind, payload = self._channel.get_nowait()
            except queue.Empty:
                return frames
            if kind == "frame":
                frames.append(payload)
            else:
                self.summary = payload
