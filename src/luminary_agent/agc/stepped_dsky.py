"""DSKY keying on a *stepped* AGC (CODE_REVIEW.md Sec.3.1).

Every keystroke is followed by stepping the AGC: a keycode waits in channel 015 until
Luminary's KEYRUPT reads it and the next write would overwrite it, so keys cannot be fired
back-to-back (found the hard way -- see tests/integration/test_stepped_mode.py).

Numeric entry is split into `enter_octal` and `enter_decimal` on purpose: P27 data words are
octal keystrokes, but V37's program number is decimal. Formatting one as the other silently
selects a different program (typing 21 through an octal formatter enters 25).

"Stepping" = the AGC is frozen and only runs when we tell it "execute N instructions"
(AgcProcess.step). So after pressing a key we must let it run a bit, or it never sees the key.
One AGC instruction takes ~11.7 microseconds, so 3000 steps ~= 35-50 ms of AGC time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess

KEY_STEPS = 3_000  # ~50 ms of AGC time: enough for KEYRUPT to consume a keycode
ENTER_STEPS = 8_000  # ENTR triggers display + program bookkeeping
FRESH_START_STEPS = 300_000  # V36E re-initialises erasable; ~3.5 s of AGC time to settle


class SteppedDsky:
    """`advance` replaces `agc.step` as the way time passes after each key. A closed-loop run
    passes the simulation's own advance here so that keystrokes move the plant too; without it
    the plant and the AGC would drift apart by ~50 ms per key pressed.
    """

    def __init__(
        self,
        agc: AgcProcess,
        client: AgcClient,
        advance: Callable[[int], Awaitable[object]] | None = None,
    ) -> None:
        if agc.mode != "stepped":
            raise ValueError("SteppedDsky drives a stepped AgcProcess")
        self.agc = agc
        self.client = client
        self._advance_hook = advance

    async def _advance(self, steps: int) -> object:
        # Resolved per call, not in __init__: the hook may be swapped, and a test double for the
        # AGC need not provide `step` at all.
        if self._advance_hook is not None:
            return await self._advance_hook(steps)
        return await self.agc.step(steps)

    async def key(self, key: str, steps: int = KEY_STEPS) -> None:
        """Press one key and let the AGC run long enough to read it."""
        await self.client.press_key(key)
        await self._advance(steps)
        await asyncio.sleep(0.005)  # let the socket reader drain any display updates

    async def enter(self, digits: str) -> None:
        """Type a string of digit keys, then ENTR."""
        for digit in digits:
            await self.key(digit)
        await self.key("ENTR", ENTER_STEPS)

    async def enter_octal(self, value: int) -> None:
        """Type `value` in base 8 (e.g. 8 -> keys "1", "0")."""
        await self.enter(f"{value:o}")

    async def enter_decimal(self, value: int) -> None:
        """Type `value` in base 10."""
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
        await self._advance(FRESH_START_STEPS)
