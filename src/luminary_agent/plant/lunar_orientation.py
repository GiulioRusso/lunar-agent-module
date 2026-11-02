"""The Moon's orientation, as Luminary computes it (PLANETARY_INERTIAL_ORIENTATION.agc, MOONMX).

Luminary keeps the landing site in Moon-fixed coordinates (RLS) and converts to its inertial
reference frame with RP-TO-R: R = M(T)^T * (RP + L x RP). M is built from the Moon's orbital
elements -- three angles, each X = X0 + Xdot * (T + T0) in revolutions:
    B      (BSUBO, BDOT)    Gamma (NODIO, NODDOT, "NODI")    F (FSUBO, FDOT)
and the inclination I of the mean lunar equator to the ecliptic:
    A = (cos G, cos B sin G, sin B sin G)
    B = (-sin G, cos B cos G, sin B cos G)
    C = (0, -sin B, cos B)
    D = B cos I - C sin I
    M2 = B sin I + C cos I        (the Moon's pole, in reference coordinates)
    M1 = A sin F - D cos F
    M0 = -(A cos F + D sin F)
The rows of M are the Moon-fixed axes expressed in the reference frame; F advances at FDOT
(2.6724e-6 rad/s), which is the rotation of the Moon about M2. Constants are copied from
CONTROLLED_CONSTANTS.agc. T0 is TEPHEM, zero after a fresh start; the libration vector
504LM is zero and is omitted.

Validation and its honest limit: fed the same RLS, REFSMMAT and time, this reproduces the
direction of the LAND vector a real yaAGC computed (tests/unit/test_lunar_orientation.py) to
~0.05% of the Moon's radius (~1 km), including the ~115 degree rotation that a naive
"Moon-fixed == inertial" assumption misses. The residual is not explained by any sign or
transposition variant tried; it is plausibly the guidance loop's own per-pass rotation of the
site. It is a measured model gap, not a claim of exactness.

Plain words: the Moon spins, so a point on its surface (the landing site) moves in inertial
space. "Moon-fixed" coordinates rotate with the Moon; "reference"/inertial ones do not. This
module gives the 3x3 rotation matrix between them at any time, exactly as the AGC computes it,
so the site we tell the AGC and the site the plant uses agree. Vectors are plain 3-tuples and
matrices 3-tuples of rows (no numpy) to mirror the flight code step by step.
"""

from __future__ import annotations

import math

TAU = 2.0 * math.pi  # one revolution in radians

# CONTROLLED_CONSTANTS.agc. Angles in revolutions; rates stored as B+28 (B+27 for FDOT) in
# revolutions per centisecond.
NODIO = 0.986209434
FSUBO = 0.829090536
BSUBO = 0.0651201393
NODDOT_REV_CS = -0.457335121e-2 / 2**28
FDOT_REV_CS = 0.570863327 / 2**27
BDOT_REV_CS = -3.07500686e-8 / 2**28
SINI = 0.02676579
COSI = 0.99964173

MOON_ROTATION_RAD_S = FDOT_REV_CS * TAU * 100.0  # 2.67240e-6, matches the source comment

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]


def _scale(v: Vec, k: float) -> Vec:
    """k * v."""
    return (v[0] * k, v[1] * k, v[2] * k)


def _add(a: Vec, b: Vec) -> Vec:
    """a + b."""
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def moon_matrix(t_cs: float, t0_cs: float = 0.0) -> Mat:
    """M(T): rows are the Moon-fixed axes in the reference frame. `t_cs` is AGC-clock time in
    centiseconds; `t0_cs` is TEPHEM (ephemeris time at AGC zero), zero after a fresh start.
    """
    t = t_cs + t0_cs
    # The three angles (revolutions -> radians), each a start value plus rate * time.
    g = (NODIO + NODDOT_REV_CS * t) * TAU
    f = (FSUBO + FDOT_REV_CS * t) * TAU
    b = (BSUBO + BDOT_REV_CS * t) * TAU
    # Build the rows exactly as in the module docstring's formulas.
    cg, sg, cb, sb = math.cos(g), math.sin(g), math.cos(b), math.sin(b)
    a_vec: Vec = (cg, cb * sg, sb * sg)
    b_vec: Vec = (-sg, cb * cg, sb * cg)
    c_vec: Vec = (0.0, -sb, cb)
    d_vec = _add(_scale(b_vec, COSI), _scale(c_vec, -SINI))
    m2 = _add(_scale(b_vec, SINI), _scale(c_vec, COSI))
    m1 = _add(_scale(a_vec, math.sin(f)), _scale(d_vec, -math.cos(f)))
    m0 = _scale(_add(_scale(a_vec, math.cos(f)), _scale(d_vec, math.sin(f))), -1.0)
    return (m0, m1, m2)


def _mv(m: Mat, v: Vec) -> Vec:
    """Matrix times vector, M v."""
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _mtv(m: Mat, v: Vec) -> Vec:
    """M^T v."""
    return (
        m[0][0] * v[0] + m[1][0] * v[1] + m[2][0] * v[2],
        m[0][1] * v[0] + m[1][1] * v[1] + m[2][1] * v[2],
        m[0][2] * v[0] + m[1][2] * v[1] + m[2][2] * v[2],
    )


def rp_to_r(rp: Vec, t_cs: float, t0_cs: float = 0.0) -> Vec:
    """Moon-fixed -> reference frame (Luminary's RP-TO-R with zero libration)."""
    return _mtv(moon_matrix(t_cs, t0_cs), rp)


def r_to_rp(r: Vec, t_cs: float, t0_cs: float = 0.0) -> Vec:
    """Reference frame -> Moon-fixed (R-TO-RP with zero libration)."""
    return _mv(moon_matrix(t_cs, t0_cs), r)
