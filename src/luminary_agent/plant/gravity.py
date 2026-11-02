"""Lunar gravity, inverse-square in altitude above a spherical Moon.

mu = 4.9028e12 m^3/s^2. R is Luminary's own Moon radius, RSUBM = 1,738,090 m ("EQUATORIAL MOON
RADIUS", CONTROLLED_CONSTANTS/504RM), not the 1,737.4 km mean radius: the flight software
measures altitude above a sphere of exactly this radius, so a plant with a different surface
would disagree with the AGC about where the ground is (690 m here) at touchdown.

Newton: g = mu / r**2, with mu = G * M_moon and r the distance from the Moon's centre.
"""

from __future__ import annotations

MU_MOON = 4.9028e12  # m^3/s^2
R_MOON = 1_738_090.0  # m


def g(altitude_m: float) -> float:
    """Gravitational acceleration (m/s^2, positive magnitude) at `altitude_m` above the
    mean lunar surface. At altitude 0 this is ~1.62 m/s^2, matching the commonly cited
    lunar surface gravity.
    """
    r = R_MOON + altitude_m  # distance from the Moon's centre
    return MU_MOON / (r * r)
