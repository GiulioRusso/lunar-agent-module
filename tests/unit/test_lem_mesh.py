"""Unit tests for the shipped LM mesh (lem/mesh.py, lem/preview.py): shape, size, and silhouettes
compared with the reference measurements in docs/lem-glb-reference.json.

Run alone: `uv run pytest tests/unit/test_lem_mesh.py -v`.
"""

import json
from pathlib import Path

import numpy as np

from luminary_agent.lem.mesh import convex_iou, load_lem_mesh
from luminary_agent.lem.preview import render

REFERENCE = json.loads((Path(__file__).parents[2] / "docs" / "lem-glb-reference.json").read_text())


def test_mesh_is_well_formed_and_small() -> None:
    m = load_lem_mesh()
    assert m.vertices.shape[1] == 3 and m.faces.shape[1] == 3 and len(m.colors) == len(m.faces)
    assert int(m.faces.max()) < len(m.vertices) and 3_000 < len(m.faces) < 15_000
    assert np.isfinite(m.vertices).all()


def test_dimensions_and_frame() -> None:
    m = load_lem_mesh()
    assert abs(m.vertices[:, 2].min()) < 0.05  # footpad soles are the ground
    assert 6.0 < m.height_m < 7.05  # antennas are dropped, so a bit under the 7.04 m overall
    assert abs(m.gear_span_m - REFERENCE["gear_span_m"]) < 0.15
    pads = m.vertices[m.vertices[:, 2] < 0.3]
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):  # one pad on each of the four axes
        assert (sign * pads[:, axis]).max() > 4.3


def test_silhouettes_match_the_reference_model() -> None:
    """The reference hulls include the antennas the mesh drops, so the floor is below 1."""
    m = load_lem_mesh()
    for view, floor in (("front", 0.85), ("side", 0.85), ("top", 0.95)):
        ref = [(x, y) for x, y in REFERENCE["hulls"][view]]
        assert convex_iou(m.silhouette(view), ref) >= floor, view


def test_render_draws_the_vehicle() -> None:
    img = render(load_lem_mesh(), 35, 18, size=160, scale=17.0)
    assert img.shape == (160, 160, 3) and (img != img[0, 0]).any(axis=2).sum() > 1_000


def test_convex_iou_is_exact_on_simple_shapes() -> None:
    a = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert convex_iou(a, a) == 1.0
    assert abs(convex_iou(a, [(1.0, 0.0), (3.0, 0.0), (3.0, 2.0), (1.0, 2.0)]) - 1 / 3) < 1e-9
    assert convex_iou(a, [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]) == 0.0
