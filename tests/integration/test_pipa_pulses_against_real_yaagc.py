"""Sends real PIPA pulses to a live yaAGC over the socket and confirms, via a core dump
snapshot, that the PIPAX register (erasable 037) actually incremented -- proof the
plant->AGC IMU wiring works end to end, independent of any Luminary guidance sequence.

Stepped mode: the pause boundary is also the I/O boundary, so send, step, then snapshot.

Integration test: starts a real yaAGC running Luminary 099 (needs `make agc` first; the module-
level `pytestmark = skipif(...)` skips every test here otherwise). Each test uses its own fixed
TCP port numbers on 127.0.0.1 so tests can run without colliding; `tmp_path` is the scratch
folder yaAGC writes its core files into. `asyncio.run(run())` drives the async API from a
plain (synchronous) pytest function.

Run alone: `uv run pytest tests/integration/test_pipa_pulses_against_real_yaagc.py -v`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.registers import REG_PIPAX

PORT = 19799

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_pipa_pulses_reach_the_real_pipax_register(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=PORT) as agc:
            await agc.step(20_000)
            async with AgcClient(port=PORT) as client:
                await client.send_pipa_pulses(REG_PIPAX, 17)
                await agc.step(20_000)  # pulses are consumed as the AGC executes
            dump = await agc.coredump()
            assert dump.erasable_signed(0, REG_PIPAX) == 17

    asyncio.run(run())
