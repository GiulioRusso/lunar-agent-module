"""Identical inputs must give identical AGC state, however loaded the machine is.

yaAGC is driven over two unordered paths (packets over TCP, commands over a pipe). Before
`agc/handshake.py` and the barriers in `patches/yaagc-free-run.patch`, whether a packet sent before
a STEP was consumed before or after it depended on scheduling: 1 in 5 copies of one full episode
diverged when run side by side. This test runs several copies of the same short input stream at
once and demands bit-identical AGC cycle counters throughout. It is probabilistic in the failing
direction (a race may not fire in one run), so a pass is evidence, not proof; the full-episode
check is `luminary eval` on the same seed twice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.registers import REG_CDUX, REG_PIPAX, REG_PIPAZ

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)

COPIES = 6
TICKS = 400
STEP_INSTRUCTIONS = 1_600  # one 20 ms tick


async def trace(workdir: Path, port: int) -> list[int]:
    """AGC cycle counter every 40 ticks of a steady stream of PIPA and CDU pulses."""
    cycles: list[int] = []
    async with AgcProcess(workdir, mode="stepped", port=port) as agc:
        await agc.step(30_000)
        async with AgcClient(port=port) as client:
            for tick in range(TICKS):
                await client.send_pipa_pulses(REG_PIPAX, 3 + tick % 5)
                await client.send_pipa_pulses(REG_PIPAZ, -(1 + tick % 3))
                await client.send_cdu_pulses(REG_CDUX, 2 if tick % 2 else -1)
                await agc.step(STEP_INSTRUCTIONS)
                if tick % 40 == 39:
                    cycles.append((await agc.coredump()).cycle_counter)
    return cycles


def test_identical_inputs_give_identical_agc_state_under_load(tmp_path: Path) -> None:
    async def run() -> list[list[int]]:
        return list(
            await asyncio.gather(*(trace(tmp_path / str(i), 19900 + 10 * i) for i in range(COPIES)))
        )

    traces = asyncio.run(run())
    assert len(traces[0]) == TICKS // 40
    assert all(t == traces[0] for t in traces), traces
