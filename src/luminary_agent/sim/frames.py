"""Plant <-> AGC reference frame.

The plant is planar in polar form (altitude, arc-length downrange, vertical and tangential
velocity). The AGC works in its Moon-centred reference frame, in which the Moon's orientation is
the matrix M(T) of plant/lunar_orientation.py. LunarFrame chooses the plant's orbit plane to be
the Moon's *equatorial* plane at a reference time, so that the Moon's rotation is a plain
in-plane rotation at MOON_ROTATION_RAD_S and the orbit is prograde with it:

  * e1 = the Moon-fixed x axis at t_ref, e2 = the direction it moves toward, pole = M row 2;
  * theta = x / R_moon is the angle swept from the plant's t0 position, measured from e1 toward
    e2; r_hat = e1 cos t + e2 sin t, t_hat = -e1 sin t + e2 cos t.

Everything the AGC is told is expressed in the reference frame through this basis:
  * state vector: position/velocity from (radial, tangential) components;
  * REFSMMAT for a landing: the *landing-site frame* -- X up at the site, Z toward the direction
    of travel (so a vehicle uprange has negative Z), Y = Z x X. IGNALG runs with the guidance
    matrix CG = identity, so RGU = R - LAND is in these axes and RIGNX/RIGNZ are altitude/range;
  * RLS: the site in Moon-fixed coordinates, R-TO-RP of its reference-frame position at the
    time Luminary evaluates RP-TO-R (TLAND). Luminary then treats the site as a fixed inertial
    point; the plant's surface rotates under it (see MOON_ROTATION_RAD_S), so it is at that
    point at TLAND.

Plain words: the physics is 2-D (a slice through the Moon), the AGC thinks in 3-D. This module
places that 2-D slice inside the AGC's 3-D space. e1 and e2 are two perpendicular unit vectors
spanning the slice; any 2-D point (x, y) becomes x*e1 + y*e2 in 3-D.
Vectors are plain tuples; dot/cross/mat_vec are the usual linear-algebra operations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from luminary_agent.agc.state_vector import StateVector
from luminary_agent.plant.dynamics import PlanarState
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.lunar_orientation import Mat, Vec, moon_matrix, r_to_rp

IDENTITY: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def dot(a: Vec, b: Vec) -> float:
    """Dot product (a . b)."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    """Cross product (a x b): perpendicular to both."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def neg(a: Vec) -> Vec:
    """-a."""
    return (-a[0], -a[1], -a[2])


def mat_vec(m: Mat, v: Vec) -> Vec:
    """Matrix (tuple of rows) times vector."""
    return (dot(m[0], v), dot(m[1], v), dot(m[2], v))


def theta_rad(state: PlanarState) -> float:
    """Angle travelled around the Moon's centre (arc length / radius)."""
    return state.x_m / R_MOON


def inertial_vector(radial: float, tangential: float, theta: float) -> tuple[float, float]:
    """In-plane (e1, e2) components of a vector given by (radial, tangential) components."""
    c, s = math.cos(theta), math.sin(theta)
    return (radial * c - tangential * s, radial * s + tangential * c)


@dataclass(frozen=True)
class LunarFrame:
    """The plant's 2-D plane inside the AGC's 3-D reference frame."""

    e1: Vec  # unit vector: plane x axis (where the plant starts, theta = 0)
    e2: Vec  # unit vector: plane y axis (90 degrees ahead, the direction of travel)

    @classmethod
    def from_moon(cls, t_ref_cs: float, t0_cs: float = 0.0) -> LunarFrame:
        """The frame in the Moon's equatorial plane at time t_ref_cs (see module docstring)."""
        m = moon_matrix(t_ref_cs, t0_cs)
        pole, e1 = m[2], m[0]
        e2 = cross(pole, e1)
        # Orient e2 toward the direction the Moon-fixed x axis actually moves, so the plant's
        # prograde direction is the Moon's spin direction whatever sign the model gives.
        later = moon_matrix(t_ref_cs + 1_000.0, t0_cs)
        if dot(later[0], e2) < 0.0:
            e2 = neg(e2)
        return cls(e1=e1, e2=e2)

    @property
    def normal(self) -> Vec:
        """Unit vector perpendicular to the plane (the orbit's angular-momentum direction)."""
        return cross(self.e1, self.e2)

    def to_ref(self, x: float, y: float) -> Vec:
        """2-D plane point/vector (x, y) -> 3-D reference vector x*e1 + y*e2."""
        return (
            self.e1[0] * x + self.e2[0] * y,
            self.e1[1] * x + self.e2[1] * y,
            self.e1[2] * x + self.e2[2] * y,
        )

    def up_and_travel(self, theta: float) -> tuple[Vec, Vec]:
        """Local "up" and "forward" unit vectors at angle theta around the Moon."""
        c, s = math.cos(theta), math.sin(theta)
        return self.to_ref(c, s), self.to_ref(-s, c)

    def site_ref(self, theta_site: float, radius_m: float = R_MOON) -> Vec:
        """3-D position of the landing site (on the surface at angle theta_site)."""
        up, _ = self.up_and_travel(theta_site)
        return (up[0] * radius_m, up[1] * radius_m, up[2] * radius_m)

    def landing_refsmmat(self, theta_site: float) -> Mat:
        """Rows are the stable-member axes in reference coordinates (X up, Y = Z x X, Z travel)."""
        up, travel = self.up_and_travel(theta_site)
        return (up, cross(travel, up), travel)

    def rls(self, theta_site: float, t_land_cs: float, t0_cs: float = 0.0) -> Vec:
        """Moon-fixed landing-site vector that RP-TO-R maps back to the site at t_land."""
        return r_to_rp(self.site_ref(theta_site), t_land_cs, t0_cs)

    def state_vector(self, state: PlanarState, t_cs: float) -> StateVector:
        """The plant's 2-D state as the 3-D StateVector the AGC is loaded with."""
        theta = theta_rad(state)
        rx, ry = inertial_vector(R_MOON + state.h_m, 0.0, theta)
        vx, vy = inertial_vector(state.hdot_ms, state.xdot_ms, theta)
        return StateVector(r_m=self.to_ref(rx, ry), v_ms=self.to_ref(vx, vy), t_cs=t_cs)

    def specific_force_ref(
        self, radial: float, tangential: float, theta: float, normal: float = 0.0
    ) -> Vec:
        """Accelerometer reading (thrust/mass) in 3-D; `normal` = out-of-plane component."""
        ax, ay = inertial_vector(radial, tangential, theta)
        x, y, z = self.to_ref(ax, ay)
        n = self.normal
        return (x + normal * n[0], y + normal * n[1], z + normal * n[2])


# The default frame for tests that do not care about the Moon: reference axes = plane axes.
PLANE_IS_XY = LunarFrame(e1=(1.0, 0.0, 0.0), e2=(0.0, 1.0, 0.0))
