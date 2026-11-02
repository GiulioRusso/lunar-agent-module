"""Extract reference measurements from a glTF/GLB model of the LM (dev tool, not used at runtime).

The GLB is a *measurement reference only*: nothing is rendered from it and it is not shipped with
the simulator. This tool reads it (Draco decode needs the optional `DracoPy`), rescales it so its
overall height equals the documented 7.04 m, and writes a small JSON of derived numbers: silhouette
hulls in three views, pad layout and a half-width profile. Tests compare the procedural model
against them. See CODE_REVIEW.md ("GLB reference").

    uv run --with DracoPy python -m luminary_agent.lem.glb_reference \
        "docs/Apollo Lunar Module.glb" docs/lem-glb-reference.json

GLB file layout (read by hand below): 12-byte header, then chunks of [length, type, data];
the "JSON" chunk describes the scene (nodes, meshes, materials), the "BIN" chunk holds the
(Draco-compressed) geometry bytes.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

from luminary_agent.lem.mesh import hull

DOC_HEIGHT_M = 7.04
VIEWS = {"front": (1, 2), "side": (0, 2), "top": (0, 1)}  # (horizontal, vertical) in model axes


def _mat(node: dict[str, Any]) -> np.ndarray:
    """4x4 transform of one glTF node (either given directly, or rotation quaternion x scale +
    translation). Multiplying parent @ child gives the node's placement in the world."""
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    m = np.eye(4)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rot = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])  # fmt: skip
    m[:3, :3] = rot * np.array(node.get("scale", [1, 1, 1]))
    m[:3, 3] = node.get("translation", [0, 0, 0])
    return m


def load_parts(path: Path) -> list[dict[str, Any]]:
    """Every primitive of the scene in world space: vertices, faces and base colour (RGB 0-1)."""
    import DracoPy  # type: ignore[import-not-found,unused-ignore]  # optional dev dependency

    data = path.read_bytes()
    off, chunks = 12, {}  # skip the 12-byte file header
    while off < len(data):
        # "<I4s": little-endian 4-byte length + 4-byte chunk type.
        n, kind = struct.unpack("<I4s", data[off : off + 8])
        chunks[kind] = data[off + 8 : off + 8 + n]
        off += 8 + n
    gltf, binary = json.loads(chunks[b"JSON"]), chunks[b"BIN\x00"]
    out: list[dict[str, Any]] = []

    # Depth-first walk of the scene tree, accumulating transforms from the root.
    def walk(i: int, parent: np.ndarray) -> None:
        node = gltf["nodes"][i]
        m = parent @ _mat(node)
        for prim in gltf["meshes"][node["mesh"]]["primitives"] if "mesh" in node else []:
            view = gltf["bufferViews"][
                prim["extensions"]["KHR_draco_mesh_compression"]["bufferView"]
            ]
            start = view.get("byteOffset", 0)
            mesh = DracoPy.decode(binary[start : start + view["byteLength"]])
            pts = np.array(mesh.points, dtype=float).reshape(-1, 3)
            material = gltf["materials"][prim["material"]] if "material" in prim else {}
            color = material.get("pbrMetallicRoughness", {}).get("baseColorFactor") or [0.55] * 4
            out.append({
                "v": (m[:3, :3] @ pts.T).T + m[:3, 3],
                "f": np.array(mesh.faces).reshape(-1, 3),
                "color": color[:3],
            })  # fmt: skip
        for child in node.get("children", []):
            walk(child, m)

    for root in gltf["scenes"][0]["nodes"]:
        walk(root, np.eye(4))
    return out


def load_vertices(path: Path) -> np.ndarray:
    """All vertices of the scene in world space, glTF axes (x right, y up, z forward here)."""
    return np.vstack([p["v"] for p in load_parts(path)])


def to_model_frame(v: np.ndarray) -> np.ndarray:
    """glTF (x, y up, z forward) -> model frame (x forward, y left, z up), metres, sole at 0."""
    y0 = v[:, 1].min()
    k = DOC_HEIGHT_M / (v[:, 1].max() - y0)
    return np.column_stack([v[:, 2] * k, v[:, 0] * k, (v[:, 1] - y0) * k])


def measure(path: Path) -> dict[str, Any]:
    """Derive the reference numbers (height, gear span, pads, silhouettes, profile)."""
    raw = load_vertices(path)
    g = to_model_frame(raw)
    k = DOC_HEIGHT_M / float(raw[:, 1].max() - raw[:, 1].min())
    # Footpads: vertices near the ground and far from the centre, grouped by direction.
    low = g[(g[:, 2] < 0.16 * k) & (np.hypot(g[:, 0], g[:, 1]) > 2.5)]
    pads = {}
    for name, sel in (("+x", low[:, 0] > 1), ("-x", low[:, 0] < -1), ("+y", low[:, 1] > 1),
                      ("-y", low[:, 1] < -1)):  # fmt: skip
        c = low[sel].mean(0)
        pads[name] = [round(float(c[0]), 2), round(float(c[1]), 2)]
    # Width of the vehicle in 0.5 m horizontal slices, bottom to top.
    profile = []
    for lo in np.arange(0.0, DOC_HEIGHT_M, 0.5):
        m = (g[:, 2] >= lo) & (g[:, 2] < lo + 0.5)
        if m.any():
            profile.append({
                "z": [round(float(lo), 2), round(float(lo + 0.5), 2)],
                "x": [round(float(g[m, 0].min()), 2), round(float(g[m, 0].max()), 2)],
                "y": [round(float(g[m, 1].min()), 2), round(float(g[m, 1].max()), 2)],
            })  # fmt: skip
    return {
        "source": path.name,
        "note": "derived numbers only; model rescaled so overall height = 7.04 m",
        "scale_to_height": round(k, 4),
        "height_m": round(float(g[:, 2].max()), 2),
        "gear_span_m": round(float(np.ptp(g[:, 1])), 2),
        "pad_centres_xy_m": pads,
        # rounded first, hulled after: rounding can leave a hair of concavity, and the IoU in
        # lem.model.convex_iou clips against these polygons, so they must be strictly convex.
        "hulls": {
            view: [
                list(p)
                for p in hull(
                    [(round(float(u), 2), round(float(w), 2)) for u, w in g[:, list(idx)]]
                )
            ]
            for view, idx in VIEWS.items()
        },
        "profile": profile,
    }


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(measure(Path(sys.argv[1])), indent=1) + "\n")
