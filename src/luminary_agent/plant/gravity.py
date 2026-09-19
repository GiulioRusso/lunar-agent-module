"""Lunar gravity, inverse-square in altitude above a spherical Moon.

Constants per APOLLO_AGENT_PLAN.md Sec.1: mu = 4.9028e12 m^3/s^2, R = 1737.4 km.
"""

from __future__ import annotations

MU_MOON = 4.9028e12  # m^3/s^2
R_MOON = 1_737_400.0  # m


def g(altitude_m: float) -> float:
    """Gravitational acceleration (m/s^2, positive magnitude) at `altitude_m` above the
    mean lunar surface. At altitude 0 this is ~1.62 m/s^2, matching the commonly cited
    lunar surface gravity.
    """
    r = R_MOON + altitude_m
    return MU_MOON / (r * r)
