"""Build the shipped low-poly LM mesh (`lem_mesh.npz`) from the NASA GLB. Dev tool, run once.

The runtime never reads the GLB: it loads the small `lem_mesh.npz` this writes. Steps (all
numeric, no model-specific hand edits):

  1. read every primitive, rescale to 7.04 m tall, model frame (x forward, y left, z up);
  2. drop what a simulation view does not need: bolts and specks (largest extent < 5 cm),
     everything whose lowest point is above the ascent-stage roof (antennas, dishes), and thin
     tall rods in the roof region (whip antennas). RCS thruster clusters are kept;
  3. simplify each part by vertex clustering (cell = 15 % of its middle extent, clamped to
     3-12 cm), so big flat panels collapse and small parts keep their shape;
  4. keep each part's material colour per face.

    uv run --with DracoPy python -m luminary_agent.lem.glb_mesh "docs/Apollo Lunar Module.glb"

Source: NASA 3D Resources, "Apollo Lunar Module" (https://science.nasa.gov/3d-resources/apollo-lunar-module/).
Credit: NASA. See CODE_REVIEW.md for the licence status.

Vocabulary: a *mesh* is a list of 3-D points (vertices, array shape (n, 3)) plus triangles
(faces, shape (m, 3): three vertex indices each). GLB = binary glTF, a standard 3-D model file.
`uv run --with DracoPy` adds the optional decoder package for that one command only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from luminary_agent.lem.glb_reference import DOC_HEIGHT_M, load_parts, to_model_frame
from luminary_agent.lem.mesh import MESH_PATH

ROOF_Z_M = 5.9  # parts wholly above this are antennas and dishes
SPECK_M = 0.05  # parts smaller than 5 cm are dropped
CELL_FRACTION, CELL_MIN_M, CELL_MAX_M = 0.15, 0.03, 0.12


def _cluster(v: np.ndarray, f: np.ndarray, cell: float) -> tuple[np.ndarray, np.ndarray]:
    """Merge vertices falling in the same grid cell; drop triangles that collapse."""
    # Integer grid cell of each vertex; `inv[i]` = which unique cell vertex i fell into.
    key, inv = np.unique(np.floor(v / cell).astype(np.int64), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    merged, count = np.zeros((len(key), 3)), np.zeros(len(key))
    # Average position of the vertices in each cell becomes the merged vertex.
    np.add.at(merged, inv, v)
    np.add.at(count, inv, 1)
    merged /= count[:, None]
    # Re-express triangles with merged indices; drop those with two corners in the same cell.
    tri = inv[f]
    tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
    if len(tri):
        tri = np.unique(np.sort(tri, axis=1), axis=0)  # duplicates go; winding is not needed
    # Renumber so only vertices still used by some triangle are kept.
    used = np.unique(tri)
    remap = -np.ones(len(merged), dtype=int)
    remap[used] = np.arange(len(used))
    return merged[used], remap[tri]


def build(glb: Path, out: Path = MESH_PATH) -> tuple[int, int]:
    """Run steps 1-4 of the module docstring; return (vertex count, triangle count)."""
    parts = load_parts(glb)
    all_v = np.vstack([p["v"] for p in parts])
    frame = to_model_frame(all_v)
    verts, faces, colors, offset, start = [], [], [], 0, 0
    for p in parts:
        n = len(p["v"])
        v = frame[start : start + n]
        start += n
        ext = np.sort(v.max(0) - v.min(0))  # bounding-box size, smallest to largest
        rod = ext[2] > 1.0 and ext[1] < 0.2 and v[:, 2].max() > 5.0
        if ext[2] < SPECK_M or v[:, 2].min() >= ROOF_Z_M or rod:
            continue
        nv, nf = _cluster(v, p["f"], float(np.clip(CELL_FRACTION * ext[1], CELL_MIN_M, CELL_MAX_M)))
        if not len(nf):
            continue
        verts.append(nv)
        faces.append(nf + offset)
        colors.append(np.tile(np.array(p["color"]) * 255, (len(nf), 1)))
        offset += len(nv)
    v_all, f_all, c_all = np.vstack(verts), np.vstack(faces), np.vstack(colors)
    # Sanity: still ~7 m tall, and few enough vertices for 16-bit indices (uint16 < 65536).
    assert abs(v_all[:, 2].max() - DOC_HEIGHT_M) < 0.7 and len(v_all) < 65536
    np.savez_compressed(
        out, vertices=v_all.astype(np.float32), faces=f_all.astype(np.uint16),
        colors=c_all.astype(np.uint8),
    )  # fmt: skip
    return len(v_all), len(f_all)


if __name__ == "__main__":
    n_v, n_f = build(Path(sys.argv[1]))
    print(f"wrote {MESH_PATH}: {n_v} vertices, {n_f} triangles, {MESH_PATH.stat().st_size} bytes")
