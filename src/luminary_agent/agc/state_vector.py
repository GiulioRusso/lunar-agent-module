"""Load a lunar-sphere LM state vector through P27 (V71).

Layout and semantics read from Luminary099: P27's V71 fills the staging buffer
UPSVFLAG(1) RRECT(6) VRECT(6) TET(2) -- exactly 15 words -- and INTWAKEU
(INTEGRATION_INITIALIZATION.agc) then acts on UPSVFLAG: negative means LM (positive CSM),
|value| == 2 means the lunar sphere of influence (1 = Earth). So LM/Moon is -2, i.e. 077775
in ones' complement. Nothing here writes memory directly; the words go in through P27.

Scales on the lunar sphere (ORBITAL_INTEGRATION.agc): position metres B-27, velocity
metres/centisecond B-5, time centiseconds B-28.
"""

from __future__ import annotations

from dataclasses import dataclass

from luminary_agent.agc.scaling import dp_from_value, dp_to_value
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.agc.uplink import Updater

UPSVFLAG_LM_MOON = 0o77775
UPSVFLAG_CSM_MOON = 0o00002  # positive = CSM; |2| = lunar sphere
POSITION_B = 27
VELOCITY_B = 5
TIME_B = 28
SV_WORDS = 15


@dataclass(frozen=True)
class StateVector:
    r_m: tuple[float, float, float]  # inertial position, metres
    v_ms: tuple[float, float, float]  # inertial velocity, metres/second
    t_cs: float  # time, centiseconds on the AGC clock

    def words(self, flag: int = UPSVFLAG_LM_MOON) -> list[int]:
        out = [flag]
        for r in self.r_m:
            out += dp_from_value(r, POSITION_B)
        for v in self.v_ms:
            out += dp_from_value(v / 100.0, VELOCITY_B)  # m/s -> m/cs
        out += dp_from_value(self.t_cs, TIME_B)
        return out

    @classmethod
    def from_words(cls, r: list[int], v: list[int], t: list[int]) -> StateVector:
        """Decode the 6+6+2 words of a stored vector (RRECTLEM, VRECTLEM, TETLEM)."""
        return cls(
            r_m=tuple(dp_to_value(r[i], r[i + 1], POSITION_B) for i in (0, 2, 4)),  # type: ignore[arg-type]
            v_ms=tuple(100.0 * dp_to_value(v[i], v[i + 1], VELOCITY_B) for i in (0, 2, 4)),  # type: ignore[arg-type]
            t_cs=dp_to_value(t[0], t[1], TIME_B),
        )


async def load_lm_state_vector(updater: Updater, symbols: SymbolTable, sv: StateVector) -> None:
    await updater.v71(symbols.ecadr("UPSVFLAG"), sv.words(UPSVFLAG_LM_MOON))


async def load_csm_state_vector(updater: Updater, symbols: SymbolTable, sv: StateVector) -> None:
    """P63 needs one: with MUNFLAG set, P41SPOT precision-integrates the CSM's state vector
    to TDEC1 (CSMPREC) before the LM's. With none loaded that integration runs on zeros and
    raises alarm 1703 ("ignition time slipped").
    """
    await updater.v71(symbols.ecadr("UPSVFLAG"), sv.words(UPSVFLAG_CSM_MOON))
