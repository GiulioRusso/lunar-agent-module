"""Unit tests for sim/clock.py RealtimeClock (wall-clock pacing and lag reporting).
These take real wall time (~0.1 s) because pacing against the wall clock is what they check.

Run alone: `uv run pytest tests/unit/test_clock.py -v`.
"""

import asyncio

from luminary_agent.sim.clock import RealtimeClock


def test_realtime_clock_paces_sim_time_to_wall_time() -> None:
    async def run() -> tuple[float, float]:
        clock = RealtimeClock()
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        for _ in range(10):
            await clock.advance(0.01)
        return loop.time() - t0, clock.sim_time_s

    wall, sim = asyncio.run(run())
    assert abs(sim - 0.10) < 1e-9
    assert 0.09 <= wall < 0.25  # paced to ~0.1 s, not free-running


def test_realtime_clock_reports_lag_when_a_tick_overruns() -> None:
    async def run() -> float:
        clock = RealtimeClock()
        await clock.advance(0.01)
        await asyncio.sleep(0.05)  # the "agent" thinks for 50 ms in a 10 ms tick
        await clock.advance(0.01)
        return clock.lag_s

    assert asyncio.run(run()) > 0.03
