"""The Apollo Lunar Module as a small triangle mesh, ready for any renderer.

`lem_mesh.npz` is built once from NASA's public 3D model of the LM (see glb_mesh.py and
CODE_REVIEW.md): ~9k flat-shaded triangles, antennas removed, RCS thruster clusters and
legs kept. Frame: metres, +x forward (toward the ladder leg), +y left, +z up, footpad soles on
z = 0, overall height 7.04 m. Load it once with `load_lem_mesh()`; it is cached.

`.npz` = numpy's zip of named arrays (np.load(...)["vertices"]). The 2-D geometry helpers below
(hull, polygon_area, convex_iou) are used by tests to compare this mesh's silhouettes with the
reference measurements in docs/lem-glb-reference.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

MESH_PATH = Path(__file__).with_name("lem_mesh.npz")  # shipped next to this file
Point = tuple[float, float, float]
Point2 = tuple[float, float]
VIEWS = {"front": (1, 2), "side": (0, 2), "top": (0, 1)}  # (horizontal, vertical) axes


@dataclass(frozen=True)
class LemMesh:
    """The loaded mesh arrays."""

    vertices: NDArray[np.float32]  # (n, 3) metres
    faces: NDArray[np.uint16]  # (m, 3) vertex indices
    colors: NDArray[np.uint8]  # (m, 3) flat colour per face

    @property
    def height_m(self) -> float:
        """Top of the highest vertex (the soles are at z = 0)."""
        return float(self.vertices[:, 2].max())

    @property
    def gear_span_m(self) -> float:
        """Outer edge to outer edge of opposite footpads (the published 'diameter')."""
        return float(np.ptp(self.vertices[:, 1]))

    def silhouette(self, view: str = "front") -> list[Point2]:
        """Convex hull of the mesh projected on a plane ('front' looks along -x, 'side' along -y,
        'top' looks down)."""
        a, b = VIEWS[view]
        return hull([(float(p[a]), float(p[b])) for p in self.vertices])


@cache  # first call loads the file; later calls return the same object
def load_lem_mesh() -> LemMesh:
    """Load lem_mesh.npz (once per process)."""
    with np.load(MESH_PATH) as data:
        return LemMesh(data["vertices"], data["faces"], data["colors"])


def hull(points: list[Point2]) -> list[Point2]:
    """Convex hull (monotone chain), counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    # >0 if o->a->b turns left (counter-clockwise), <0 right, 0 straight.
    def cross(o: Point2, a: Point2, b: Point2) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # Build the lower (then upper) chain, discarding points that make a right turn.
    def half(seq: list[Point2]) -> list[Point2]:
        out: list[Point2] = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def _pairs(poly: list[Point2]) -> list[tuple[Point2, Point2]]:
    """Consecutive edges of a closed polygon: (p0,p1), (p1,p2), ..., (pn,p0)."""
    return list(zip(poly, poly[1:] + poly[:1], strict=True))


def polygon_area(poly: list[Point2]) -> float:
    """Shoelace formula."""
    return 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in _pairs(poly)))


def _clip_edge(poly: list[Point2], p: Point2, q: Point2) -> list[Point2]:
    """Keep the part of `poly` on the left of the directed edge p->q."""

    def side(pt: Point2) -> float:
        return (q[0] - p[0]) * (pt[1] - p[1]) - (q[1] - p[1]) * (pt[0] - p[0])

    def cut(s: Point2, e: Point2) -> Point2:
        t = side(s) / (side(s) - side(e))
        return (s[0] + t * (e[0] - s[0]), s[1] + t * (e[1] - s[1]))

    out: list[Point2] = []
    for s, e in _pairs(poly):
        if side(e) >= 0:
            if side(s) < 0:
                out.append(cut(s, e))
            out.append(e)
        elif side(s) >= 0:
            out.append(cut(s, e))
    return out


def convex_iou(a: list[Point2], b: list[Point2]) -> float:
    """Intersection over union of two strictly convex polygons (Sutherland-Hodgman clipping)."""

    def ccw(poly: list[Point2]) -> list[Point2]:
        return poly if sum(u[0] * v[1] - v[0] * u[1] for u, v in _pairs(poly)) > 0 else poly[::-1]

    a, b = ccw(a), ccw(b)
    # Clip polygon a by every edge of b: what remains is the intersection a AND b.
    clipped = a
    for p, q in _pairs(b):
        if len(clipped) < 3:
            break
        clipped = _clip_edge(clipped, p, q)
    inter = polygon_area(clipped) if len(clipped) > 2 else 0.0
    union = polygon_area(a) + polygon_area(b) - inter
    return inter / union if union else 0.0
