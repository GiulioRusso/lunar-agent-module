"""Confirms the core-dump polling mechanism (coredump.py) works against a real running
yaAGC + Luminary099 in realtime mode, not just synthetic files -- the reason
CoreDumpPoller exists (see coredump.py: the socket alone can't see the DPS throttle
register). Skipped if the binaries aren't built.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.coredump import THRUST_REGISTER, CoreDumpPoller
from luminary_agent.agc.process import AgcProcess, artifacts_present

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_core_dump_parses_and_matches_expected_shape(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="realtime", port=19798):
            poller = CoreDumpPoller(path=tmp_path / "core", interval_s=0.1)
            poller.start()
            try:
                for _ in range(50):
                    if poller.latest is not None:
                        break
                    await asyncio.sleep(0.1)
                dump = poller.latest
                assert dump is not None, "yaAGC never produced a complete core dump in time"
                assert len(dump.channels) == 512
                assert len(dump.erasable) == 8
                assert len(dump.erasable[0]) == 0o400
                assert dump.cycle_counter > 0
                # Engine never ignited in this test, so the DPS throttle register reads zero.
                assert dump.erasable_signed(*THRUST_REGISTER) == 0
            finally:
                poller.stop()

    asyncio.run(run())
