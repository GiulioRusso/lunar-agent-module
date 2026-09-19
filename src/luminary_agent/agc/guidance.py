"""What the descent guidance is commanding, read from the AGC once per guidance cycle.

Three quantities, all plain erasables (never on the socket):
  THRUST   a signed thrust *increment* in counts (PIF = FC - FP) -- see plant/throttle.py;
  TTHROT   AGC-clock stamp (TIME1) of the last throttle command, written by the same routine
           (`DOIT ... CA TIME1 / TS TTHROT`). It changes exactly when a new THRUST is issued.
           This is the trigger: CHAN14 bit 4 ("thrust drive") is NOT -- Luminary latches it on at
           fresh start (`WOR CHAN14 # TURN ON THRUST DRIVE`) and merely re-asserts it on every
           command, so there is no edge to count after the first (an earlier version counted
           edges and silently missed every throttle command after the first two);
  UNFC/2   the thrust command vector in stable-member axes, three double-precision words,
           "need not be unitized" (FINDCDUW turns it into the CDU angles the DAP flies to).

With no attitude dynamics the plant treats the vehicle as *perfectly pointed* along UNFC/2. That
is a stepping stone (the real DAP takes seconds to slew and rings about its deadband) and any
result that depends on it must say so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from luminary_agent.agc.coredump import THRUST_REGISTER, CoreDump
from luminary_agent.agc.scaling import dp_to_value
from luminary_agent.agc.symbols import SymbolTable

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class GuidanceSample:
    thrust_increment_counts: int
    thrust_direction_sm: Vec | None  # unit vector, or None if the command is (still) zero
    command_stamp: int = 0  # TTHROT: differs from the last one iff a new command was issued


def read_guidance(dump: CoreDump, symbols: SymbolTable) -> GuidanceSample:
    words = dump.ecadr_words(symbols.ecadr("UNFC/2"), 6)
    v = (
        dp_to_value(words[0], words[1], 1),
        dp_to_value(words[2], words[3], 1),
        dp_to_value(words[4], words[5], 1),
    )
    norm = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    direction: Vec | None = (v[0] / norm, v[1] / norm, v[2] / norm) if norm > 1e-6 else None
    stamp = dump.ecadr_words(symbols.ecadr("TTHROT"), 1)[0]
    return GuidanceSample(dump.erasable_signed(*THRUST_REGISTER), direction, stamp)
