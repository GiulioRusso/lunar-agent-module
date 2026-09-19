"""Seeded episode dispersions: the plant's truth differs from what the AGC was told.

Each dispersion is a difference between the world and Luminary's belief about it (the AGC is
loaded with the nominal state vector and mass; only the plant deviates), which is what makes an
episode a decision problem rather than a replay. An error in the start state is never corrected by
the AGC -- there is no landing-radar model yet -- so `dh0_m` lands the vehicle high or low by that
much unless someone intervenes.

Tiers (frozen eval sets are `sample(seed, tier)` for fixed seeds; never re-draw after tuning):
  1  gentle: thrust +-0.5 %, velocity error 0.005 m/s
  2  moderate: thrust +-1.5 %, 10 m altitude error, 0.02 m/s velocity error
  3  hard: thrust +-3 %, 30 m altitude error, 0.05 m/s velocity error
Scale is set by physics, not taste: with no landing-radar update the AGC never learns a start-state
error, and a velocity error grows to ~700 m of position error per m/s over the descent (measured:
0.32 m/s made the AGC hover at 406 m until the propellant ran out; 1 m/s crashed 850 m short).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import DescentEngine

_TIERS = {  # (thrust_frac, dh_m, dv_ms, mass_frac)
    1: (0.005, 0.0, 0.005, 0.01),
    2: (0.015, 10.0, 0.02, 0.03),
    3: (0.03, 30.0, 0.05, 0.05),
}


@dataclass(frozen=True)
class Dispersion:
    thrust_scale: float = 1.0
    mass_scale: float = 1.0
    dh0_m: float = 0.0
    dvt0_ms: float = 0.0
    dvh0_ms: float = 0.0

    def engine(self) -> DescentEngine:
        e = DescentEngine()
        return replace(e, f_max_n=e.f_max_n * self.thrust_scale)

    def apply(self, s: PlanarState) -> PlanarState:
        return PlanarState(
            s.h_m + self.dh0_m,
            s.x_m,
            s.hdot_ms + self.dvh0_ms,
            s.xdot_ms + self.dvt0_ms,
            s.mass_kg * self.mass_scale,
        )


def sample(seed: int, tier: int) -> Dispersion:
    thrust, dh, dv, mass = _TIERS[tier]
    rng = random.Random(f"{tier}:{seed}")
    return Dispersion(
        1.0 + rng.uniform(-thrust, thrust),
        1.0 + rng.uniform(-mass, mass),
        rng.uniform(-dh, dh),
        rng.uniform(-dv, dv),
        rng.uniform(-dv, dv),
    )
