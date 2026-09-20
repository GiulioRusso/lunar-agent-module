"""Seeded episode dispersions: the plant's truth differs from what the AGC was told.

Each dispersion is a difference between the world and Luminary's belief about it (the AGC is
loaded with the nominal state vector and mass; only the plant deviates), which is what makes an
episode a decision problem rather than a replay. An error in the start state is never corrected by
the AGC -- there is no landing-radar model yet -- so `dh0_m` lands the vehicle high or low by that
much unless someone intervenes.

Tiers (frozen eval sets are `sample(seed, tier)` for fixed seeds; never re-draw after tuning):
  1  gentle: thrust +-0.5 %, velocity error 0.005 m/s, up to 2 % less propellant
  2  moderate: thrust +-1.5 %, 10 m altitude error, 0.02 m/s, up to 5 % less propellant
  3  hard: thrust +-3 %, 100 m altitude error, 0.3 m/s, up to 9 % less propellant (a navigation
     error the AGC cannot see: only a crew reading the radar can land it -- sim/manual_control)
Tier 3 also has a radar dead band (no lock over a 150-250 m altitude span somewhere in 100-400 m)
and every tier a small radar bias. The propellant shortfall is the margin a real crew watched
(Apollo 11 landed with ~25 s left): the engine cuts off when the usable propellant is gone.
Scale is set by physics, not taste: with no landing-radar update the AGC never learns a start-state
error, and a velocity error grows to ~700 m of position error per m/s over the descent (measured:
0.32 m/s made the AGC hover at 406 m until the propellant ran out; 1 m/s crashed 850 m short).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.radar import Radar

LOADED_MASS_KG = 15_000.0
NOMINAL_PROPELLANT_KG = 8_200.0  # usable descent propellant; the nominal landing leaves ~570 kg

_TIERS = {  # (thrust_frac, dh_m, dv_ms, mass_frac, propellant_shortfall_frac)
    1: (0.005, 0.0, 0.005, 0.01, 0.02),
    2: (0.015, 10.0, 0.02, 0.03, 0.05),
    3: (0.03, 100.0, 0.3, 0.05, 0.09),
}


@dataclass(frozen=True)
class Dispersion:
    thrust_scale: float = 1.0
    mass_scale: float = 1.0
    dh0_m: float = 0.0
    dvt0_ms: float = 0.0
    dvh0_ms: float = 0.0
    propellant_scale: float = 1.0
    radar: Radar = Radar()

    @property
    def dry_mass_kg(self) -> float:
        """Mass at which the propellant runs out: the loaded mass minus the usable propellant."""
        return LOADED_MASS_KG - NOMINAL_PROPELLANT_KG * self.propellant_scale

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
    thrust, dh, dv, mass, prop = _TIERS[tier]
    rng = random.Random(f"{tier}:{seed}")
    rr = random.Random(f"radar:{tier}:{seed}")  # separate stream: keeps the draws above stable
    hi = rr.uniform(250.0, 400.0)
    radar = Radar(
        dropout_hi_m=hi if tier == 3 else 0.0,
        dropout_lo_m=hi - rr.uniform(150.0, 250.0) if tier == 3 else 0.0,
        bias_frac=rr.uniform(-0.01, 0.01) * tier,
        seed=seed,
    )
    return Dispersion(
        1.0 + rng.uniform(-thrust, thrust),
        1.0 + rng.uniform(-mass, mass),
        rng.uniform(-dh, dh),
        rng.uniform(-dv, dv),
        rng.uniform(-dv, dv),
        1.0 - rng.uniform(0.0, prop),
        radar,
    )
