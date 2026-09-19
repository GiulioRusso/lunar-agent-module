"""Sub-gate 1b (part): the landing pad-load set goes in through P27 and every word reads back.

Values come from external/virtualagc/Luminary069/PADLOADS.agc (Apollo 10's software: the same
guidance family as Luminary 99 but NOT Apollo 11's loads -- see padloads.py), landing mode
ONE-PHASE. TLAND has no documented value and is scenario-supplied, so it is excluded here.
Slow by nature (~70 words typed at DSKY speed against a wall-clock-paced AGC): about 2 minutes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.loads import padload_words, plan_loads, run_plan
from luminary_agent.agc.padloads import PADLOADS_PATH, load_padloads
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.agc.uplink import Updater

pytestmark = pytest.mark.skipif(
    not artifacts_present() or not PADLOADS_PATH.exists(),
    reason="yaAGC / Luminary099 rope or virtualagc submodule not available -- run `make agc`",
)


def test_landing_padloads_land_in_erasable_and_raise_no_alarm(tmp_path: Path) -> None:
    sym = load_symbols(listing_path())
    entries = {name: p.words for name, p in load_padloads().items() if p.is_landing and p.words}
    words = padload_words(sym, entries)
    plan = plan_loads(words)
    failreg = sym.ecadr("FAILREG")

    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19860) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19860) as client:
                await SteppedDsky(agc, client).fresh_start()
                await run_plan(Updater(agc, client), plan)
                await agc.step(60_000)
                dump = await agc.coredump()

                wrong = {
                    oct(e): (oct(want), oct(dump.ecadr_words(e, 1)[0]))
                    for e, want in words.items()
                    if dump.ecadr_words(e, 1)[0] != want
                }
                assert not wrong, f"{len(wrong)} of {len(words)} words differ: {wrong}"
                assert dump.ecadr_words(failreg, 3) == [0, 0, 0], "an alarm was raised"

    asyncio.run(run())
    assert len(words) >= 60  # guard against the catalogue silently parsing to almost nothing
