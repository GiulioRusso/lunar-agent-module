"""Keyboard actions advance only through the normal plant/AGC loop, with real display feedback."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.plant.discretes import Discretes
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.policies.base import dsky_key
from luminary_agent.sim.clock import SteppedClock
from luminary_agent.sim.executor import Executor
from luminary_agent.sim.frames import IDENTITY, PLANE_IS_XY
from luminary_agent.sim.loop import PipaAxes, Simulation

pytestmark = pytest.mark.skipif(not artifacts_present(), reason="run make agc first")


def test_keyboard_action_reaches_real_agc_without_skipping_plant_ticks(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=31220) as agc:
            await agc.step(30_000)
            async with AgcClient(port=31220) as client:
                await SteppedDsky(agc, client).fresh_start()
                await client.write_channels(Discretes().channel_words())
                await agc.step(60_000)
                clock = SteppedClock(agc)
                await clock.start()
                sim = Simulation(
                    client,
                    clock,
                    PlanarState(15000, 0, 0, math.sqrt(MU_MOON / (R_MOON + 15000)), 15000),
                    PipaAxes(0o37, 0o40, 0o41),
                    PLANE_IS_XY,
                    IDENTITY,
                )
                executor = Executor(sim, client)
                for key in ("VERB", "1", "6", "NOUN", "3", "6", "ENTR"):
                    before = clock.sim_time_s
                    result = await executor.execute(dsky_key(before + 5, key))
                    assert result.status == "submitted"
                    assert clock.sim_time_s == before
                    await sim.run(0.2)
                await sim.run(2.0)
                assert client.dsky.verb_number == 16
                assert client.dsky.noun_number == 36
                assert sim.ticks == 170
                assert abs(clock.drift_s) < 0.05

    asyncio.run(run())
