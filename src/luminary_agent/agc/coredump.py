"""Parser for yaAGC's periodic core-dump file (agc_engine_init.c: MakeCoreDump).

Why this exists: yaAGC's socket protocol only ever broadcasts genuine channel writes
(agc_engine.c:659, ChannelOutput is called from the channel-write instruction path).
It never exposes plain erasable-memory cells. Luminary099's DPS throttle command (the
"THRUST" register, erasable address 055 -- see THROTTLE_CONTROL_ROUTINES.agc's `TS
THRUST`) is exactly such a cell: agc_engine.h explicitly comments "055-056 are spares",
meaning it has no special hardware-counter behaviour and is never involved in a channel
write, so it can never appear on the socket. Polling the periodic core dump
(yaAGC's own --dump-time option, already there for crash recovery) is the documented,
non-invasive way to see it without patching the pinned emulator submodule.

File format (agc_engine_init.c:MakeCoreDump), one 6-digit octal number per line:
  NUM_CHANNELS (512) lines -- current value of every I/O channel register
  8 banks * 0400 (256) words -- Erasable[bank][word]
  (remaining lines are CPU state we don't need here)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

NUM_CHANNELS = 512
NUM_BANKS = 8
WORDS_PER_BANK = 0o400

# Luminary099 THROTTLE_CONTROL_ROUTINES.agc: `TS THRUST` into ERASABLE_ASSIGNMENTS.agc's
# `THRUST EQUALS 55` (octal), bank 0 (all of erasable bank 0 is the low, fixed-address
# region where the special/spare hardware registers live).
THRUST_REGISTER = (0, 0o55)


def decode_agc_word(raw: int) -> int:
    """Decode a raw 15-bit AGC word (0..0o77777) as ones'-complement signed."""
    return raw if raw <= 0o37777 else raw - 0o77777


# agc_engine.h: AGC_PER_SECOND = (1024000 + 6) / 12 (integer division) machine cycles per second.
AGC_CYCLES_PER_SECOND = 85333


@dataclass(frozen=True)
class CoreDump:
    channels: tuple[int, ...]  # raw values, index = channel number
    erasable: tuple[tuple[int, ...], ...]  # erasable[bank][word], raw values
    cycle_counter: int = 0  # AGC machine cycles executed since power-on

    def erasable_signed(self, bank: int, word: int) -> int:
        return decode_agc_word(self.erasable[bank][word])

    @property
    def agc_time_s(self) -> float:
        """Simulated AGC time, from the cycle counter -- unlike TIME1/TIME2 (10 ms ticks)
        this has instruction-level resolution, so it is what the clock calibrates against.
        """
        return self.cycle_counter / AGC_CYCLES_PER_SECOND


def parse_core_dump(path: str | Path) -> CoreDump:
    """Parse a core-dump file. Raises ValueError if it's truncated (e.g. read mid-write
    by yaAGC) -- callers polling a live file should treat that as "try again next tick".
    """
    tokens = Path(path).read_text().split()
    needed = NUM_CHANNELS + NUM_BANKS * WORDS_PER_BANK
    if len(tokens) < needed:
        raise ValueError(f"truncated core dump: got {len(tokens)} values, need >= {needed}")
    values = [int(tok, 8) for tok in tokens[:needed]]
    channels = tuple(values[:NUM_CHANNELS])
    flat_erasable = values[NUM_CHANNELS:]
    erasable = tuple(
        tuple(flat_erasable[b * WORDS_PER_BANK : (b + 1) * WORDS_PER_BANK])
        for b in range(NUM_BANKS)
    )
    cycle_counter = int(tokens[needed], 8) if len(tokens) > needed else 0
    return CoreDump(channels=channels, erasable=erasable, cycle_counter=cycle_counter)


@dataclass
class CoreDumpPoller:
    """Periodically re-parses a live core-dump file yaAGC is writing (--dump-time=N).

    A read racing yaAGC's own fwrite loop can see a truncated file; that's treated as
    "no update this tick" rather than an error, since the next poll will see it complete.
    """

    path: Path
    interval_s: float = 0.2
    latest: CoreDump | None = field(default=None, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def _poll_loop(self) -> None:
        while True:
            try:
                self.latest = parse_core_dump(self.path)
            except (OSError, ValueError):
                pass
            await asyncio.sleep(self.interval_s)

    def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    @property
    def thrust_register_signed(self) -> int | None:
        if self.latest is None:
            return None
        return self.latest.erasable_signed(*THRUST_REGISTER)
