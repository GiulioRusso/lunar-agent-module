"""IMU model: specific force -> PIPA pulses, angle rate -> CDU pulses.

APOLLO_AGENT_PLAN.md Phase 1 flags this as "the most failure-prone module in the
project" and says to unit-test it against analytic constant-acceleration cases before
ever wiring it to the AGC -- see tests/unit/test_sensors.py. This module is deliberately
just the physics + quantization; the socket-level encoding of a pulse as an
UnprogrammedIncrement packet (channel = 0x80 | register, value = PINC/MINC) is a
separate, later step (external/virtualagc/yaAGC/agc_engine.c:UnprogrammedIncrement).

Scale factors:
  PIPA: 0.0585 ft/s per pulse (external/virtualagc/Contributed/LM_Simulator/lm_simulator.tcl,
  PIPA_INCR) -- the one AGC-adjacent source in this repo that states it numerically.
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

FT_TO_M = 0.3048
PIPA_SCALE_MS = 0.0585 * FT_TO_M  # m/s per pulse
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
