"""AGC-side inputs P63 needs beyond the pad loads and the state vector (all loaded via P27).

REFSMMAT  3x3 DP matrix, row-major, elements stored halved (B1: the only reading that lets a
          unit element fit; Luminary's comments say "2(-1)"). Identity puts the stable member
          on the inertial reference frame (see sim/frames.py).
REFSMFLG  bit 13 of FLAGWRD3 (REFSMBIT). P63's first act (R02BOTH) raises alarm 220 and
          aborts to P00 without it. V72 overwrites a whole word, so it is read-modify-write.
RLS       landing-site vector, Moon-fixed, metres B-27 (settled from P57's VSL2 before
          R-TO-RP "gets RLS B-27" and P52LS's VSR2 before LAT-LONG). With zero libration and
          a ~10 minute horizon RP-TO-R is the identity to ~2 mrad (lunar rotation), below
          anything this plant resolves, so Moon-fixed == inertial here.
TLAND     nominal time of landing, AGC-clock centiseconds B-28 (double precision).
"""

from __future__ import annotations

from collections.abc import Sequence

from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.scaling import dp_from_value
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.agc.uplink import Updater

REFSMMAT_B = 1
RLS_B = 27
TLAND_B = 28

IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

# FLAGWORD_ASSIGNMENTS.agc: "REFSMFLG 047 -- BIT 13 FLAG 3 -- REFSMBIT". REFSMBIT itself is an
# EQUALS to a fixed-memory constant word, so it is not resolvable from the symbol table; bit 13
# (1-based, LSB = 1) is mask 1 << 12 == 0o10000, which PADLOADS.agc also gives as "10000 FOR
# REFSMMAT GOOD".
REFSMBIT_MASK = 1 << 12


def refsmmat_words(matrix: Sequence[Sequence[float]]) -> list[int]:
    words: list[int] = []
    for row in matrix:
        for element in row:
            words += dp_from_value(element, REFSMMAT_B)
    return words


def rls_words(site_m: Sequence[float]) -> list[int]:
    words: list[int] = []
    for component in site_m:
        words += dp_from_value(component, RLS_B)
    return words


def tland_words(t_cs: float) -> list[int]:
    return list(dp_from_value(t_cs, TLAND_B))


async def set_flag_bit(
    updater: Updater, agc: AgcProcess, symbols: SymbolTable, word_name: str, mask: int
) -> None:
    """OR a flag bit into a flag word via P27 without disturbing the other flags."""
    ecadr = symbols.ecadr(word_name)
    current = (await agc.coredump()).ecadr_words(ecadr, 1)[0]
    await updater.v72([(ecadr, current | mask)])
