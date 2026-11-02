"""Turn a {ecadr: word} map into the fewest P27 sessions, then run them.

Every P27 session has a fixed cost (verb, count, verify, executive settle), so words that sit
next to each other are sent as V71 contiguous blocks and the stragglers are batched into V72
scatter loads. Limits are P27's own (see uplink.py): a V71 block is <= 18 words and may not
cross an erasable bank; a V72 load is <= 9 (address, value) pairs. Runs shorter than
MIN_RUN go to V72, where the per-word cost is lower than starting a block for them.

"ECADR" = an erasable-memory address (symbols.py). Input: {address: 15-bit word to store}.
Example: {100: a, 101: b, 102: c, 200: d} -> one V71 block [100..102] + one V72 with (200, d).
"""

from __future__ import annotations

from dataclasses import dataclass

from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.agc.uplink import MAX_V71_WORDS, MAX_V72_PAIRS, Updater

MIN_RUN = 3  # shortest run worth a V71 block
WORDS_PER_BANK = 0o400  # 256


@dataclass(frozen=True)
class LoadPlan:
    """The P27 sessions to run: contiguous blocks first, then scatter batches."""

    blocks: tuple[tuple[int, tuple[int, ...]], ...]  # V71: (start ecadr, words)
    scatters: tuple[tuple[tuple[int, int], ...], ...]  # V72: batches of (ecadr, word)

    @property
    def sessions(self) -> int:
        """How many P27 sessions this plan costs."""
        return len(self.blocks) + len(self.scatters)


def _runs(words: dict[int, int]) -> list[list[int]]:
    """Maximal groups of consecutive ecadrs that stay inside one bank."""
    runs: list[list[int]] = []
    for ecadr in sorted(words):
        # Extend the current run if this address directly follows it and does not start a new
        # bank (address % 256 == 0 is the first word of a bank); otherwise start a new run.
        if runs and ecadr == runs[-1][-1] + 1 and ecadr % WORDS_PER_BANK != 0:
            runs[-1].append(ecadr)
        else:
            runs.append([ecadr])
    return runs


def plan_loads(words: dict[int, int]) -> LoadPlan:
    """Split {ecadr: word} into V71 blocks (runs >= MIN_RUN, cut at 18 words) and V72 batches."""
    blocks: list[tuple[int, tuple[int, ...]]] = []
    stragglers: list[tuple[int, int]] = []
    for run in _runs(words):
        if len(run) < MIN_RUN:
            stragglers += [(e, words[e]) for e in run]
            continue
        for i in range(0, len(run), MAX_V71_WORDS):  # cut long runs into 18-word chunks
            chunk = run[i : i + MAX_V71_WORDS]
            if len(chunk) < MIN_RUN:  # a short tail of a long run
                stragglers += [(e, words[e]) for e in chunk]
            else:
                blocks.append((chunk[0], tuple(words[e] for e in chunk)))
    # Group the leftovers 9 pairs at a time (the V72 limit).
    scatters = tuple(
        tuple(stragglers[i : i + MAX_V72_PAIRS]) for i in range(0, len(stragglers), MAX_V72_PAIRS)
    )
    return LoadPlan(tuple(blocks), scatters)


async def run_plan(updater: Updater, plan: LoadPlan) -> None:
    """Execute a plan on the AGC, one P27 session after another."""
    for start, block in plan.blocks:
        await updater.v71(start, block)
    for batch in plan.scatters:
        await updater.v72(batch)


def padload_words(symbols: SymbolTable, entries: dict[str, tuple[int, ...]]) -> dict[int, int]:
    """Expand {symbol name: words} to {ecadr: word}. Unknown symbols are an error, not a skip."""
    out: dict[int, int] = {}
    for name, words in entries.items():
        base = symbols.ecadr(name)
        for i, w in enumerate(words):
            out[base + i] = w
    return out
