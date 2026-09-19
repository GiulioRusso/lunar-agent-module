"""DPS throttle actuator: integrates the AGC's thrust *increments*.

Luminary's THROTTLE routine computes PIF = FC - FP (desired minus present thrust, in counts)
and stores it in the THRUST register, then strobes CHAN14 bit 4 (THROTTLE_CONTROL_ROUTINES.agc).
So the register is an increment, not a level. The hardware applies it by slewing the throttle
at FRATE = 32 counts per centisecond (same file); FLATOUT commands +4096 counts to slam the
engine to its upper stop. One count is 12.533 N (propulsion.THRUST_N_PER_COUNT).

Modelled here: increments accumulate as a pending command, thrust slews toward it at the rate
limit, and thrust is clamped between the minimum firing throttle and the fixed upper detent
(FMAX). Engine ON starts the engine at minimum throttle (Luminary holds minimum for
ZOOMTIME seconds after ignition before throttling up); OFF drops thrust to zero. Behaviour in the
60%-92.5% unstable band is not modelled: the flight software avoids commanding it (LOWCRIT/
HIGHCRIT), and a slewing throttle only crosses it transiently.
"""

from __future__ import annotations

from dataclasses import dataclass

from luminary_agent.plant.propulsion import (
    F_MAX_N,
    FMAX_DETENT_N,
    THROTTLE_MIN,
    THRUST_N_PER_COUNT,
)

SLEW_COUNTS_PER_S = 32 * 100  # FRATE: 32 counts per centisecond
MIN_COUNTS = THROTTLE_MIN * F_MAX_N / THRUST_N_PER_COUNT
MAX_COUNTS = FMAX_DETENT_N / THRUST_N_PER_COUNT


@dataclass
class ThrottleActuator:
    counts: float = 0.0  # present thrust, in AGC counts
    pending: float = 0.0  # commanded change not yet slewed in
    engine_on: bool = False

    def set_engine(self, on: bool) -> None:
        if on and not self.engine_on:
            self.counts = MIN_COUNTS
            self.pending = 0.0
        elif not on:
            self.counts = 0.0
            self.pending = 0.0
        self.engine_on = on

    def command(self, increment_counts: float) -> None:
        """Apply one THRUST-register increment (the value read at a CHAN14 bit-4 strobe)."""
        if self.engine_on:
            self.pending += increment_counts

    def step(self, dt_s: float) -> None:
        if not self.engine_on or self.pending == 0.0:
            return
        limit = SLEW_COUNTS_PER_S * dt_s
        move = max(-limit, min(limit, self.pending))
        self.counts += move
        self.pending -= move
        if self.counts >= MAX_COUNTS or self.counts <= MIN_COUNTS:
            self.counts = max(MIN_COUNTS, min(MAX_COUNTS, self.counts))
            self.pending = 0.0  # against a stop: leftover command is discarded, not wound up

    @property
    def thrust_n(self) -> float:
        return self.counts * THRUST_N_PER_COUNT

    @property
    def throttle_fraction(self) -> float:
        """Thrust as a fraction of 100%, for DescentEngine.thrust_and_mdot."""
        return self.thrust_n / F_MAX_N
