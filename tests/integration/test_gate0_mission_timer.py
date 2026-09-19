"""GATE 0 (APOLLO_AGENT_PLAN.md Sec.5): key V16N65 from Python and watch the AGC's mission
timer tick. Noun 65 is "SAMPLED AGC TIME (HRS,MIN,SEC)" -- confirmed against
external/virtualagc/Luminary099/PINBALL_NOUN_TABLES.agc. R1/R2/R3 after V16N65 are
hours/minutes/seconds, so R2:R3 must advance once the AGC is running.

Realtime mode (`--nodebug`, AGC free-runs). Requires `make agc`; skipped otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present

PORT = 19797

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_gate0_mission_timer_ticks(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="realtime", port=PORT):
            async with AgcClient(port=PORT) as agc:
                await agc.key_sequence(["VERB", "1", "6", "ENTR", "NOUN", "6", "5", "ENTR"])
                await asyncio.sleep(0.5)  # let the first display update land
                assert agc.dsky.verb_number == 16
                assert agc.dsky.noun_number == 65

                first = (agc.dsky.r2, agc.dsky.r3)
                await asyncio.sleep(2.0)
                second = (agc.dsky.r2, agc.dsky.r3)

                assert None not in first and None not in second, (
                    f"mission timer never rendered: first={first} second={second}"
                )
                assert first != second, "mission timer did not tick in 2s of wall-clock time"

    asyncio.run(run())
