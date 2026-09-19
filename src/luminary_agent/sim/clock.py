"""Simulation clocks (APOLLO_AGENT_PLAN.md Sec.3.1).

Design rule: nothing outside this module may sleep, read the wall clock, or assume sim-time
equals wall-time. Everything else receives `dt` from a clock and asks it to `advance`.

RealtimeClock -- sim-time is paced against the wall clock; the AGC free-runs (`--nodebug`)
                 and the agent races it. `lag_s` records how far behind schedule we are.
SteppedClock  -- the AGC executes only when stepped, so *not* advancing the clock pauses the
                 whole simulation (an agent may think as long as it likes). Advancing by
                 `dt` runs enough AGC instructions to cover it. Instructions do not have a
                 fixed length (~1.6 cycles each, measured), so the instruction count per tick
                 is calibrated against the AGC's own cycle counter, and any residual drift
                 between plant time and AGC time is exposed rather than hidden.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from luminary_agent.agc.coredump import AGC_CYCLES_PER_SECOND
from luminary_agent.agc.process import AgcProcess

INITIAL_CYCLES_PER_INSTRUCTION = 1.62  # measured on Luminary099 idle; recalibrated live


class SimClock(Protocol):
    sim_time_s: float

    async def advance(self, dt_s: float) -> None:
        """Move simulation time forward by dt_s (and the AGC with it)."""
        ...


class RealtimeClock:
    def __init__(self) -> None:
        self.sim_time_s = 0.0
        self.lag_s = 0.0  # >0: behind schedule (the tick took longer than dt allowed)
        self._origin: float | None = None

    async def advance(self, dt_s: float) -> None:
        loop = asyncio.get_running_loop()
        if self._origin is None:
            self._origin = loop.time()
        self.sim_time_s += dt_s
        remaining = self._origin + self.sim_time_s - loop.time()
        self.lag_s = max(0.0, -remaining)
        if remaining > 0:
            await asyncio.sleep(remaining)


class SteppedClock:
    def __init__(self, agc: AgcProcess, calibrate_every_s: float = 1.0) -> None:
        self.agc = agc
        self.calibrate_every_s = calibrate_every_s
        self.sim_time_s = 0.0
        self.cycles_per_instruction = INITIAL_CYCLES_PER_INSTRUCTION
        self._origin_cycles = 0
        self._est_cycles = 0.0  # AGC cycles, extrapolated between calibrations
        self._sync_cycles = 0
        self._sync_instructions = 0
        self._last_sync_sim_s = 0.0

    @property
    def drift_s(self) -> float:
        """AGC time minus plant time (estimated between calibrations). Should hover near 0."""
        agc_s = (self._est_cycles - self._origin_cycles) / AGC_CYCLES_PER_SECOND
        return agc_s - self.sim_time_s

    async def start(self) -> None:
        """Anchor the clock to the AGC's current cycle count. Call once, after boot."""
        dump = await self.agc.coredump()
        self._origin_cycles = self._est_cycles = self._sync_cycles = dump.cycle_counter

    async def _calibrate(self) -> None:
        dump = await self.agc.coredump()
        if self._sync_instructions > 0:
            self.cycles_per_instruction = (
                dump.cycle_counter - self._sync_cycles
            ) / self._sync_instructions
        self._est_cycles = float(dump.cycle_counter)
        self._sync_cycles = dump.cycle_counter
        self._sync_instructions = 0
        self._last_sync_sim_s = self.sim_time_s

    async def advance(self, dt_s: float) -> None:
        self.sim_time_s += dt_s
        target_cycles = self._origin_cycles + self.sim_time_s * AGC_CYCLES_PER_SECOND
        needed_cycles = target_cycles - self._est_cycles
        instructions = max(1, round(needed_cycles / self.cycles_per_instruction))
        await self.agc.step(instructions)
        self._est_cycles += instructions * self.cycles_per_instruction
        self._sync_instructions += instructions
        if self.sim_time_s - self._last_sync_sim_s >= self.calibrate_every_s:
            await self._calibrate()
