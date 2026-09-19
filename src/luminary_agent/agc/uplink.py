"""Erasable-memory loads through Luminary's own update program, P27 (verbs 71 and 72).

This is "erasable init via the uplink path, not by poking memory" (APOLLO_AGENT_PLAN.md
Phase 1): the words go in through the real flight software, which validates them, is restart-
protected, and complements a downlink flag to say the update happened.

P27's data entry is transport-agnostic -- ground uplink and DSKY keystrokes feed the same
buffer -- so this drives it through the DSKY we already have. Protocol, read from
external/virtualagc/Luminary099/UPDATE_PROGRAM.agc and confirmed against a live yaAGC:

  V71E  II E  AAAA E  XXXXX E ... XXXXX E   V33E        contiguous block
        II   = number of data words + 2 (octal); 3 <= II <= 20 decimal
        AAAA = ECADR of the first word (see symbols.py)
  V72E  II E  AAAA E XXXXX E  AAAA E XXXXX E ...  V33E   scatter (address, value) pairs
        II   = 2 * pairs + 1 (octal), odd; 3 <= II <= 19

Data are unsigned octal (noun 01), <= 5 digits. V33E after the last entry is the "verify"
that makes P27 actually store. P27 is only accepted in P00; elsewhere it raises OPERATOR ERROR.

Keystrokes go through SteppedDsky, which steps the AGC after each one (see there for why).
"""

from __future__ import annotations

from collections.abc import Sequence

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.stepped_dsky import SteppedDsky

MAX_V71_COMPONENTS = 20  # UPDATE_PROGRAM.agc: UP21 = 21 = "max no of components + 1"
MAX_V72_COMPONENTS = 19
MAX_V71_WORDS = MAX_V71_COMPONENTS - 2
MAX_V72_PAIRS = (MAX_V72_COMPONENTS - 1) // 2

VERIFY_STEPS = 30_000  # V33E performs the actual store (restart-protected, so slower)


class UpdateError(ValueError):
    pass


def _check_word(value: int, what: str) -> None:
    if not 0 <= value <= 0o77777:
        raise UpdateError(f"{what} {value:#o} is not a 15-bit word")


class Updater:
    """Drive P27 on a *stepped* AgcProcess through an AgcClient connected to it."""

    def __init__(self, agc: AgcProcess, client: AgcClient) -> None:
        if agc.mode != "stepped":
            raise UpdateError("P27 loads are driven by stepping; use a stepped AgcProcess")
        self.agc = agc
        self.client = client
        self.dsky = SteppedDsky(agc, client)

    async def v71(self, ecadr: int, words: Sequence[int]) -> None:
        """Load `words` into consecutive erasable words starting at `ecadr`."""
        if not 1 <= len(words) <= MAX_V71_WORDS:
            raise UpdateError(f"V71 takes 1..{MAX_V71_WORDS} words per load, got {len(words)}")
        if not 0 <= ecadr <= 0o3777:
            raise UpdateError(f"ECADR {ecadr:#o} out of range")
        if (ecadr & 0o377) + len(words) > 0o400:
            raise UpdateError("a V71 block may not run past the end of its erasable bank")
        for w in words:
            _check_word(w, "data word")
        await self.dsky.verb(71)
        await self.dsky.enter_octal(len(words) + 2)
        await self.dsky.enter_octal(ecadr)
        for w in words:
            await self.dsky.enter_octal(w)
        await self._verify()

    async def v72(self, pairs: Sequence[tuple[int, int]]) -> None:
        """Load (ecadr, value) pairs to arbitrary erasable locations."""
        if not 1 <= len(pairs) <= MAX_V72_PAIRS:
            raise UpdateError(f"V72 takes 1..{MAX_V72_PAIRS} pairs per load, got {len(pairs)}")
        for ecadr, value in pairs:
            if not 0 <= ecadr <= 0o3777:
                raise UpdateError(f"ECADR {ecadr:#o} out of range")
            _check_word(value, "data word")
        await self.dsky.verb(72)
        await self.dsky.enter_octal(2 * len(pairs) + 1)
        for ecadr, value in pairs:
            await self.dsky.enter_octal(ecadr)
            await self.dsky.enter_octal(value)
        await self._verify()

    async def _verify(self) -> None:
        await self.dsky.verb(33)
        await self.agc.step(VERIFY_STEPS)
        await self.agc.step(VERIFY_STEPS)  # let the job finish and P27 exit
