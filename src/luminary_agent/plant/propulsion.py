"""LM Descent Propulsion System (DPS): throttle law and mass flow.

Approximate Apollo-11-class constants (APOLLO_AGENT_PLAN.md Phase 1); Phase 2 replaces
these with cited NTRS/Apollo-11-Mission-Report values as part of the flight-context
taxonomy work -- these are physically-reasonable placeholders, not sourced numbers.

The DPS is not continuously throttleable across its whole range: it can be commanded
anywhere from 10%-60% of rated thrust, but between 60% and a fixed ~92.5% detent the
engine is unstable and jumps straight to the detent (APOLLO_AGENT_PLAN.md Sec.5, Phase 1).
"""

from __future__ import annotations

from dataclasses import dataclass

G0 = 9.80665  # m/s^2, standard gravity used to define specific impulse

ISP_S = 311.0  # vacuum specific impulse, s
THROTTLE_MIN = 0.10
THROTTLE_MAX_VARIABLE = 0.60
THROTTLE_FIXED_DETENT = 0.925

# Thrust as Luminary's throttle software counts it. Three independent (count, force) pairs
# annotated in the flight-software source agree to 0.02%:
#   FMAXPOS  DEC +3467 B-14   "FMAX +4.34546769 E+4"   (THROTTLE_CONTROL / CONTROLLED_CONSTANTS)
#   FMAXODD  DEC +3841 B-14   "FSAT +4.81454413 E+4"
#   FEXTRA = BIT13 = 4096     "FEXT +5.13309020 E+4"    (THROTTLE_CONTROL_ROUTINES.agc)
# giving ~12.533 N per count (2.82 lbf; the PADLOADS comment's "2.7 lbf/bit" is a rounding).
# FMAX is the thrust at the fixed 92.5% detent, which puts 100% at 46.98 kN -- within 0.6% of
# the DPS's rated ~46.7 kN. (An earlier placeholder here, 43.9 kN, was FMAX mistaken for 100%.)
FMAX_DETENT_N = 43_454.6769
THRUST_N_PER_COUNT = 12.5334
F_MAX_N = FMAX_DETENT_N / THROTTLE_FIXED_DETENT  # 100% thrust, N


def resolve_throttle(commanded: float) -> float:
    """Map a commanded throttle fraction [0, 1] to the fraction the DPS can actually hold.

    0 -> engine off. (0, 0.10) -> clamped up to the minimum firing throttle. [0.10, 0.60]
    -> held as commanded. (0.60, 1.0] -> snaps to the fixed ~92.5% detent, since the
    engine cannot hold anything between 60% and the detent.
    """
    if commanded <= 0.0:
        return 0.0
    if commanded < THROTTLE_MIN:
        return THROTTLE_MIN
    if commanded <= THROTTLE_MAX_VARIABLE:
        return commanded
    return THROTTLE_FIXED_DETENT


@dataclass(frozen=True)
class DescentEngine:
    f_max_n: float = F_MAX_N
    isp_s: float = ISP_S

    def thrust_and_mdot(self, commanded_throttle: float) -> tuple[float, float]:
        """Return (thrust_N, mass_flow_kg_s) for a commanded throttle fraction.

        Mass flow is positive (propellant consumed), i.e. dm/dt = -mdot.
        """
        throttle = resolve_throttle(commanded_throttle)
        thrust_n = throttle * self.f_max_n
        mdot = thrust_n / (G0 * self.isp_s)
        return thrust_n, mdot
