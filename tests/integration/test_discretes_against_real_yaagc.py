"""Writes hardware discretes into a live AGC and confirms Luminary's own T4RUPT monitor
(IMUMON, every 480 ms) mirrors them into IMODES30 -- so the polarity and bit positions in
plant/discretes.py are checked against the flight software, not just against the docs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.plant.discretes import Discretes

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)

IMU_OPERATE_BIT = 1 << 8  # bit 9
IMU_CAGE_BIT = 1 << 10  # bit 11


def test_luminary_mirrors_imu_discretes_into_imodes30(tmp_path: Path) -> None:
    ecadr = load_symbols(listing_path()).ecadr("IMODES30")

    async def imodes30(agc: AgcProcess) -> int:
        return (await agc.coredump()).erasable[ecadr // 0o400][ecadr % 0o400]

    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19831) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19831) as client:
                # Cold AGC: nothing asserted, IMU reads as not operating (bit 9 == 1).
                await client.write_channels(Discretes(imu_operate=False).channel_words())
                await agc.step(80_000)  # > one 480 ms T4RUPT IMU monitor cycle
                assert await imodes30(agc) & IMU_OPERATE_BIT != 0

                await client.write_channels(Discretes(imu_operate=True).channel_words())
                await agc.step(80_000)
                assert await imodes30(agc) & IMU_OPERATE_BIT == 0, "IMU operate never mirrored"

    asyncio.run(run())
