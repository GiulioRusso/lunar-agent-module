"""Gate 1a (CODE_REVIEW.md ledger): plant coasting, discretes asserted, AGC alive in
P00 with no alarms, every tick recorded, plant and AGC time together.

The plant starts on a circular orbit at 15 km, i.e. at PDI-like speed with no thrust: a flat
plant would plunge, the spherical one must hold altitude -- so this doubles as an end-to-end
check that the polar dynamics are what the loop actually runs.

Integration test: starts a real yaAGC running Luminary 099 (needs `make agc` first; the module-
level `pytestmark = skipif(...)` skips every test here otherwise). Each test uses its own fixed
TCP port numbers on 127.0.0.1 so tests can run without colliding; `tmp_path` is the scratch
folder yaAGC writes its core files into. `asyncio.run(run())` drives the async API from a
plain (synchronous) pytest function.

Run alone: `uv run pytest tests/integration/test_sim_loop_coasting.py -v`.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.registers import REG_PIPAX, REG_PIPAY, REG_PIPAZ
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.plant.discretes import Discretes
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON
from luminary_agent.sim.clock import SteppedClock
from luminary_agent.sim.frames import IDENTITY, PLANE_IS_XY
from luminary_agent.sim.loop import PipaAxes, Simulation
from luminary_agent.sim.recorder import Recorder, read_episode

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_coasting_episode_is_recorded_and_the_agc_stays_quiet(tmp_path: Path) -> None:
    symbols = load_symbols(listing_path())
    failreg = symbols.ecadr("FAILREG")
    h0 = 15_000.0
    v_circ = math.sqrt(MU_MOON / (R_MOON + h0))
    log = tmp_path / "episode.jsonl.gz"

    async def run() -> None:
        async with AgcProcess(tmp_path / "agc", mode="stepped", port=19832) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19832) as client:
                # Cold boot leaves alarm 1107 (phase-table failure) from the first restart;
                # a crew fresh-starts after power-up, so do that and start from a clean slate.
                await SteppedDsky(agc, client).fresh_start()
                await client.write_channels(Discretes().channel_words())
                await agc.step(60_000)
                clock = SteppedClock(agc)
                await clock.start()
                header = {"scenario": "coast-1a", "clock": "stepped", "seed": 0}
                with Recorder(log, header) as rec:
                    sim = Simulation(
                        client,
                        clock,
                        PlanarState(h0, 0.0, 0.0, v_circ, 15_000.0),
                        PipaAxes(x=REG_PIPAX, y=REG_PIPAY, z=REG_PIPAZ),
                        PLANE_IS_XY,
                        IDENTITY,
                        recorder=rec,
                    )
                    await sim.run(3.0)

                assert abs(sim.state.h_m - h0) < 1.0  # spherical plant holds the orbit
                assert abs(clock.drift_s) < 0.05
                dump = await agc.coredump()
                alarm_words = [
                    dump.erasable[failreg // 0o400][failreg % 0o400 + i] for i in range(3)
                ]
                assert alarm_words == [0, 0, 0], f"program alarm raised: {alarm_words}"

    asyncio.run(run())

    header, ticks = read_episode(log)
    records = list(ticks)
    assert header["scenario"] == "coast-1a"
    assert len(records) == 150
    assert records[0]["t"] == pytest.approx(0.02)
    assert records[-1]["t"] == pytest.approx(3.0)
    assert all(r["pipa_pulses"] == [0, 0, 0] for r in records)
    assert all(abs(r["h_m"] - h0) < 1.0 for r in records)
