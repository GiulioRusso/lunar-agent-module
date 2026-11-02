"""Where the wall clock actually goes in a run (CODE_REVIEW.md Phase S, lever 2).

A descent runs at well under real time, and the plan's instruction is explicit: profile before
optimising, and publish the split. This is the smallest thing that does it -- a wall-time
accumulator per named section, always on (a few microseconds per tick), reported with every
episode so a speed-up is a number in the log rather than an impression.

Sections are named for what the time is spent *on*, not where the code lives:
  step      stepping yaAGC through the debugger pipe (one round trip per tick)
  guidance  the core dump taken to read THRUST / UNFC-2 while the engine burns
  alarms    the once-a-second core dump that reads FAILREG / MODREG
  pipa      accelerometer pulses written to the AGC's counters
  plant     the RK4 integration and the IMU model
  record    writing the episode log

Usage:  `with meter.section("plant"): ...code...` -> the time spent inside is added to "plant".
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class Meter:
    """Named wall-time accumulators (a tiny profiler)."""

    def __init__(self) -> None:
        self.totals: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self._start = time.perf_counter()

    # @contextmanager turns this generator into something usable with `with`: code before
    # `yield` runs on entry, the `finally` block on exit (even if an exception is raised).
    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.totals[name] = self.totals.get(name, 0.0) + elapsed
            self.counts[name] = self.counts.get(name, 0) + 1

    @property
    def wall_s(self) -> float:
        """Wall seconds since this Meter was created."""
        return time.perf_counter() - self._start

    def report(self, sim_s: float) -> dict[str, float | dict[str, float]]:
        """Wall seconds per section, what fraction of the run each took, and the speed the whole
        thing ran at. `sim_s` is simulated seconds covered."""
        wall = self.wall_s
        measured = sum(self.totals.values())
        sections = {k: round(v, 2) for k, v in sorted(self.totals.items(), key=lambda kv: -kv[1])}
        return {
            "wall_s": round(wall, 1),
            "sim_s": round(sim_s, 1),
            "speed_x_real_time": round(sim_s / wall, 2) if wall > 0 else 0.0,
            "sections_s": sections,
            # Whatever is left is Python between the sections: asyncio, bookkeeping, the policy.
            "unattributed_s": round(wall - measured, 1),
        }
