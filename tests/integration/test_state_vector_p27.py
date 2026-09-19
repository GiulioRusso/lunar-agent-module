"""Sub-gate 1b (part): an LM state vector goes in through P27 and Luminary's own INTWAKEU
installs it as the permanent LM state vector (RRECTLEM/VRECTLEM/TETLEM). Reading those back
is proof the flight software accepted it -- we never write them ourselves.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.state_vector import StateVector, load_lm_state_vector
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.agc.uplink import Updater
from luminary_agent.plant.gravity import MU_MOON, R_MOON

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_lm_state_vector_is_installed_by_the_flight_software(tmp_path: Path) -> None:
    sym = load_symbols(listing_path())
    r = R_MOON + 15_000.0
    v = math.sqrt(MU_MOON / r)

    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19850) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19850) as client:
                await SteppedDsky(agc, client).fresh_start()
                now_cs = (await agc.coredump()).clock_cs
                sent = StateVector(r_m=(r, 0.0, 0.0), v_ms=(0.0, v, 0.0), t_cs=float(now_cs))
                await load_lm_state_vector(Updater(agc, client), sym, sent)
                await agc.step(60_000)  # INTWAKEU is a job; give the executive time to run it
                dump = await agc.coredump()

                got = StateVector.from_words(
                    dump.ecadr_words(sym.ecadr("RRECTLEM"), 6),
                    dump.ecadr_words(sym.ecadr("VRECTLEM"), 6),
                    dump.ecadr_words(sym.ecadr("TETLEM"), 2),
                )
                assert got.r_m == pytest.approx(sent.r_m, abs=1.0)
                assert got.v_ms == pytest.approx(sent.v_ms, abs=0.01)
                assert got.t_cs == pytest.approx(sent.t_cs, abs=1.0)
                # INTWAKEU clears the request flag once it has consumed the update.
                assert dump.ecadr_words(sym.ecadr("UPSVFLAG"), 1) == [0]

    asyncio.run(run())
