"""DSKY keying on a *stepped* AGC (APOLLO_AGENT_PLAN.md Sec.3.1).

Every keystroke is followed by stepping the AGC: a keycode waits in channel 015 until
Luminary's KEYRUPT reads it and the next write would overwrite it, so keys cannot be fired
back-to-back (found the hard way -- see tests/integration/test_stepped_mode.py).

Numeric entry is split into `enter_octal` and `enter_decimal` on purpose: P27 data words are
octal keystrokes, but V37's program number is decimal. Formatting one as the other silently
selects a different program (typing 21 through an octal formatter enters 25).
"""

from __future__ import annotations

import asyncio

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess

KEY_STEPS = 3_000  # ~50 ms of AGC time: enough for KEYRUPT to consume a keycode
ENTER_STEPS = 8_000  # ENTR triggers display + program bookkeeping
FRESH_START_STEPS = 300_000  # V36E re-initialises erasable; ~3.5 s of AGC time to settle


class SteppedDsky:
    def __init__(self, agc: AgcProcess, client: AgcClient) -> None:
        if agc.mode != "stepped":
            raise ValueError("SteppedDsky drives a stepped AgcProcess")
        self.agc = agc
        self.client = client

    async def key(self, key: str, steps: int = KEY_STEPS) -> None:
        await self.client.press_key(key)
        await self.agc.step(steps)
        await asyncio.sleep(0.005)  # let the socket reader drain any display updates

    async def enter(self, digits: str) -> None:
        for digit in digits:
            await self.key(digit)
        await self.key("ENTR", ENTER_STEPS)

    async def enter_octal(self, value: int) -> None:
        await self.enter(f"{value:o}")

    async def enter_decimal(self, value: int) -> None:
        await self.enter(str(value))

    async def verb(self, verb: int) -> None:
        """Key VERB <verb> ENTR (verbs are decimal)."""
        await self.key("VERB")
        for digit in str(verb):
            await self.key(digit)
        await self.key("ENTR", ENTER_STEPS)

    async def fresh_start(self) -> None:
        """V36E. A cold AGC boots with zeroed erasable, so its first restart raises alarm 1107
        (phase-table failure) into FAILREG. A crew would fresh-start after power-up; this
        does the same and leaves FAILREG clear so later alarms are unambiguous.
        """
        await self.verb(36)
        await self.agc.step(FRESH_START_STEPS)
