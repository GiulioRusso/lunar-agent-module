"""Regression: back-to-back STEP commands across parallel yaAGC never stall.

The upstream `nbfgets` input thread had a lost-wakeup race (patches/yaagc-free-run.patch): with
commands arriving back to back under CPU load, ~1 in 16 processes stopped reading its pipe and the
caller's STEP timed out. The stall is probabilistic, so a pass is evidence, not proof.

Integration test: starts a real yaAGC running Luminary 099 (needs `make agc` first; the module-
level `pytestmark = skipif(...)` skips every test here otherwise). Each test uses its own fixed
TCP port numbers on 127.0.0.1 so tests can run without colliding; `tmp_path` is the scratch
folder yaAGC writes its core files into. `asyncio.run(run())` drives the async API from a
plain (synchronous) pytest function.

Run alone: `uv run pytest tests/integration/test_stepped_stress.py -v`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.process import AgcProcess, artifacts_present

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)

PROCESSES = 16
STEPS = 4000


async def _storm(workdir: Path, port: int) -> int:
    async with AgcProcess(workdir, mode="stepped", port=port) as agc:
        for done in range(STEPS):
            try:
                await agc._command("STEP 1", timeout_s=10.0)
            except TimeoutError:
                return done
    return STEPS


def test_step_storm_does_not_stall(tmp_path: Path) -> None:
    async def run() -> list[int]:
        dirs = []
        for i in range(PROCESSES):
            (tmp_path / str(i)).mkdir()
            dirs.append(tmp_path / str(i))
        return await asyncio.gather(*(_storm(d, 31000 + 10 * i) for i, d in enumerate(dirs)))

    assert asyncio.run(run()) == [STEPS] * PROCESSES
