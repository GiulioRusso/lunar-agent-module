"""Landing-radar altitude as an agent sees it: a bias, a little noise, and a band of true
altitude where it has no lock (dust, antenna position, late lock-on -- a recurring real problem).

This feeds the *observation* only. The AGC is not given radar data (yaAGC's socket build has no
radar path), so a large disagreement between the AGC's altitude and the radar's is exactly the
1969 crew's decision: which one to believe.

Determinism: the noise uses a random generator seeded from (seed, time), so the same scenario
and time always give the same reading -- episodes are reproducible bit for bit.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Radar:
    """Radar error model; the defaults are "healthy". dispersions.py sets the faulty ones."""

    dropout_hi_m: float = 0.0  # no lock while dropout_lo_m <= true altitude <= dropout_hi_m
    dropout_lo_m: float = 0.0
    bias_frac: float = 0.0
    noise_frac: float = 0.005
    noise_m: float = 1.0
    seed: int = 0

    def altitude(self, true_h_m: float, t_s: float) -> float | None:
        """Measured altitude at time t_s, or None when the radar has no lock."""
        if self.dropout_lo_m <= true_h_m <= self.dropout_hi_m:
            return None
        rng = random.Random(f"{self.seed}:{t_s:.1f}")
        sigma = self.noise_m + self.noise_frac * abs(true_h_m)  # noise grows with altitude
        return true_h_m * (1.0 + self.bias_frac) + rng.gauss(0.0, sigma)
