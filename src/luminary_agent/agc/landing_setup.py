"""AGC-side inputs P63 needs beyond the pad loads and the state vector (all loaded via P27).

REFSMMAT  3x3 DP matrix, row-major, elements stored halved (B1: the only reading that lets a
          unit element fit; Luminary's comments say "2(-1)"). For P63 it must be the
          *landing-site frame*: X up at the site, Z toward the direction of travel, Y = Z x X.
          IGNALG runs with the guidance matrix CG = identity, so RGU = R - LAND is expressed in
          stable-member axes, and RIGNX/RIGNZ ("altitude", "ground range") only mean something
          in that frame. Identity is fine for coasting tests but wrong for P63.
REFSMFLG  bit 13 of FLAGWRD3 (REFSMBIT). P63's first act (R02BOTH) raises alarm 220 and
          aborts to P00 without it. V72 overwrites a whole word, so it is read-modify-write.
RLS       landing-site vector, **Moon-fixed**, metres B-27 (settled from P57's VSL2 before
          R-TO-RP "gets RLS B-27" and P52LS's VSR2 before LAT-LONG). It is NOT the inertial
          site vector: RP-TO-R rotates it through MOONMX, the Moon's real orientation matrix
          (orbital elements BSUBO/FSUBO/NODIO/SINI... plus time since epoch), which is nowhere
          near identity. An earlier version of this docstring claimed it was identity to ~2
          mrad; that was wrong, and it is why IGNALG diverged. A consistent RLS needs that
          matrix -- see APOLLO_AGENT_PLAN.md, Gate 1 ledger, "lunar orientation".
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
