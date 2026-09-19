"""V71/V72 erasable loads through Luminary's real P27, against a live yaAGC.

Targets are erasable words 055 and 056, which agc_engine.h marks "spares" (no hardware
behaviour attached), so a stray write cannot disturb anything the AGC is doing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess, artifacts_present
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.agc.uplink import Updater

pytestmark = pytest.mark.skipif(
    not artifacts_present(), reason="yaAGC / Luminary099 rope not built -- run `make agc` first"
)


def test_v71_loads_a_contiguous_block(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19821) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19821) as client:
                await Updater(agc, client).v71(0o55, [0o12345, 0o07070])
            dump = await agc.coredump()
            assert dump.erasable[0][0o55] == 0o12345
            assert dump.erasable[0][0o56] == 0o07070

    asyncio.run(run())


def test_v72_loads_scattered_pairs(tmp_path: Path) -> None:
    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19822) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19822) as client:
                await Updater(agc, client).v72([(0o56, 0o00111), (0o55, 0o77000)])
            dump = await agc.coredump()
            assert dump.erasable[0][0o56] == 0o00111
            assert dump.erasable[0][0o55] == 0o77000

    asyncio.run(run())


def test_p27_refuses_outside_p00_and_writes_nothing(tmp_path: Path) -> None:
    """P27 is only accepted in P00. Leave P00 (V37E 25E -- P25 engages from a cold AGC and
    sticks), confirm we really left via MODREG, then check the load is refused rather than
    half-applied.

    Note V37's program number is *decimal* keystrokes, unlike P27's octal data words.
    """
    modreg_ecadr = load_symbols(listing_path()).ecadr("MODREG")

    async def modreg(agc: AgcProcess) -> int:
        dump = await agc.coredump()
        return dump.erasable_signed(*divmod(modreg_ecadr, 0o400))

    async def run() -> None:
        async with AgcProcess(tmp_path, mode="stepped", port=19823) as agc:
            await agc.step(30_000)
            async with AgcClient(port=19823) as client:
                up = Updater(agc, client)
                assert await modreg(agc) == 0  # starts in P00
                await up._verb(37)
                for digit in "25":
                    await up._key(digit)
                await up._key("ENTR", 8_000)
                await agc.step(60_000)
                assert await modreg(agc) == 25, "precondition: failed to leave P00"

                await up.v71(0o55, [0o1234])
            dump = await agc.coredump()
            assert dump.erasable[0][0o55] != 0o1234, "P27 accepted a load outside P00"

    asyncio.run(run())
