"""IMU model: specific force -> PIPA pulses, angle rate -> CDU pulses.

APOLLO_AGENT_PLAN.md Phase 1 flags this as "the most failure-prone module in the
project" and says to unit-test it against analytic constant-acceleration cases before
ever wiring it to the AGC -- see tests/unit/test_sensors.py. This module is deliberately
just the physics + quantization; the socket-level encoding of a pulse as an
UnprogrammedIncrement packet (channel = 0x80 | register, value = PINC/MINC) is a
separate, later step (external/virtualagc/yaAGC/agc_engine.c:UnprogrammedIncrement).

Scale factors:
  PIPA: 0.01 m/s (1 cm/s) per pulse -- read off Luminary's own constants, not a document:
  CONTROLLED_CONSTANTS.agc `KPIP1 2DEC .0128 # SCALES DELV TO UNITS OF 2(7) M/CS`, with DELV the
  pulse count scaled 2**-14, so one pulse = 2**-14 * .0128 * 2**7 = 1.0e-4 m/cs = 0.01 m/s.
  CORRECTION: an earlier version used 0.0585 ft/s (1.78 cm/s) from the Tcl LM_Simulator stub.
  0.0585 is the *Command Module's* 5.85 cm/s in m/s, and its units were mislabelled by me.
  The closed-loop descent exposed it: fed 1.78 cm/s pulses, the AGC sensed only ~half the
  true deceleration and under-braked.
  CDU: 360/32768 deg per pulse, i.e. a full 15-bit-counter revolution -- cross-checked
  against the same file's comment "39.55078125'' of arc" (360*3600/32768 == 39.55078125).

A PIPA is a true integrator: it accumulates specific force continuously and only ever
outputs whole pulses, carrying the fractional remainder forward. PulseCounter models
that residual explicitly so a sustained sub-threshold acceleration still eventually
produces pulses, instead of being silently rounded to zero every step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PIPA_SCALE_MS = 0.01  # m/s per pulse (see module docstring)
CDU_SCALE_RAD = math.radians(360.0 / 32768.0)  # rad per pulse


@dataclass
class PulseCounter:
    """Quantizes a continuously-integrated quantity (velocity, angle) into signed
    pulses of size `scale`, keeping the fractional remainder between calls.
    """

    scale: float
    _residual: float = field(default=0.0, init=False)

    def pulses_for(self, delta: float) -> int:
        """Fold in `delta` (already in the same units as scale*pulses, e.g. a velocity
        increment for a PIPA) and return the signed whole-pulse count emitted now.
        """
        total = self._residual + delta / self.scale
        pulses = math.trunc(total)
        self._residual = total - pulses
        return pulses


@dataclass
class Imu:
    """Three PIPAs (stable-member X, Y, Z) and one CDU axis. The PIPAs sit on the stable member,
    so they measure specific force in *stable-member* axes (sim/frames.py: REFSMMAT times the
    reference-frame vector), not along the vehicle's local vertical, which rotates as it orbits.
    """

    pipa: tuple[PulseCounter, PulseCounter, PulseCounter] = field(
        default_factory=lambda: (
            PulseCounter(PIPA_SCALE_MS),
            PulseCounter(PIPA_SCALE_MS),
            PulseCounter(PIPA_SCALE_MS),
        )
    )
    cdu_pitch: PulseCounter = field(default_factory=lambda: PulseCounter(CDU_SCALE_RAD))

    def sample(
        self,
        specific_force_sm: tuple[float, float, float],
        pitch_rate_rad_s: float,
        dt_s: float,
    ) -> tuple[tuple[int, int, int], int]:
        """One sample over `dt_s`: returns ((pipa_x, pipa_y, pipa_z) pulses, cdu pulses)."""
        pulses = (
            self.pipa[0].pulses_for(specific_force_sm[0] * dt_s),
            self.pipa[1].pulses_for(specific_force_sm[1] * dt_s),
            self.pipa[2].pulses_for(specific_force_sm[2] * dt_s),
        )
        return pulses, self.cdu_pitch.pulses_for(pitch_rate_rad_s * dt_s)
