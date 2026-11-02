"""Analytic Kepler orbits, to construct consistent starting states for the plant.

A landing scenario cannot start from an arbitrary state: Luminary's ignition algorithm (IGNALG)
searches along the state vector's *own orbit* for the ignition time at which the vehicle is at
the pad-loaded ground range, altitude and speed relative to the landing site
(RIGNZ / RIGNX / VIGN). A circular orbit at PDI altitude flies ~16 m/s slower than VIGN at
every point, and no choice of time can null a constant offset -- IGNALG raises alarm 1412
"not converging". So the start must be a descent *ellipse* whose perilune state matches.

Notation: rp/ra are perilune/apolune radii from the Moon's centre, nu is true anomaly
(0 at perilune, negative before it), r/vr/vt are radius, radial and tangential velocity.

Plain words: before the descent engine fires, the LM coasts on an ellipse around the Moon whose
lowest point (perilune, ~15 km up) is where Powered Descent Initiation (PDI) happens. This file
is textbook two-body orbital mechanics (Kepler) used to compute that coasting state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import MU_MOON, R_MOON


@dataclass(frozen=True)
class DescentOrbit:
    """An ellipse around the Moon, given by its lowest and highest radius (from the centre)."""

    rp_m: float  # perilune radius
    ra_m: float  # apolune radius

    @property
    def a_m(self) -> float:
        """Semi-major axis (average of the two extreme radii)."""
        return 0.5 * (self.rp_m + self.ra_m)

    @property
    def e(self) -> float:
        """Eccentricity: 0 = circle, closer to 1 = more elongated."""
        return (self.ra_m - self.rp_m) / (self.ra_m + self.rp_m)

    @property
    def h_m2s(self) -> float:
        """Specific angular momentum."""
        return math.sqrt(MU_MOON * self.a_m * (1.0 - self.e**2))

    @property
    def perilune_speed_ms(self) -> float:
        """Speed at the lowest point (fastest point of the orbit)."""
        return self.h_m2s / self.rp_m

    def radius_at(self, nu: float) -> float:
        """Distance from the Moon's centre at true anomaly nu (the orbit equation)."""
        return self.a_m * (1.0 - self.e**2) / (1.0 + self.e * math.cos(nu))

    def velocity_at(self, nu: float) -> tuple[float, float]:
        """(radial, tangential) velocity, m/s."""
        vr = MU_MOON / self.h_m2s * self.e * math.sin(nu)
        vt = self.h_m2s / self.radius_at(nu)
        return vr, vt

    def time_to_perilune_s(self, nu: float) -> float:
        """Seconds until perilune from true anomaly nu (negative nu -> positive time)."""
        # Kepler's equation: true anomaly -> eccentric anomaly -> mean anomaly -> time.
        e = self.e
        ecc_anom = 2.0 * math.atan2(
            math.sqrt(1.0 - e) * math.sin(nu / 2.0), math.sqrt(1.0 + e) * math.cos(nu / 2.0)
        )
        mean_anom = ecc_anom - e * math.sin(ecc_anom)
        n = math.sqrt(MU_MOON / self.a_m**3)  # mean motion, rad/s
        return -mean_anom / n

    def state_at(self, nu: float, mass_kg: float) -> PlanarState:
        """The plant state (downrange 0) at true anomaly nu."""
        vr, vt = self.velocity_at(nu)
        return PlanarState(
            h_m=self.radius_at(nu) - R_MOON, x_m=0.0, hdot_ms=vr, xdot_ms=vt, mass_kg=mass_kg
        )

    @classmethod
    def with_perilune_speed(cls, perilune_alt_m: float, speed_ms: float) -> DescentOrbit:
        """The ellipse whose perilune, at the given altitude, has the given speed (solves for
        apolune from vis-viva: v^2 = mu (2/rp - 1/a)).
        """
        rp = R_MOON + perilune_alt_m
        inv_a = 2.0 / rp - speed_ms**2 / MU_MOON
        if inv_a <= 0.0:
            raise ValueError("that speed is escape speed or more at this altitude")
        return cls(rp_m=rp, ra_m=2.0 / inv_a - rp)
