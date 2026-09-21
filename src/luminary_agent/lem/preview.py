"""Flat-shaded PNG of the LM mesh (three-quarter, rear, side) for a quick visual check.

Pure numpy + zlib, painter's algorithm; the real renderer is the S3 window.

    python -m luminary_agent.lem.preview out.png
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from luminary_agent.lem.mesh import LemMesh, load_lem_mesh

LIGHT = np.array([-0.4, -0.6, 0.7]) / np.linalg.norm([-0.4, -0.6, 0.7])


def render(
    mesh: LemMesh, azimuth_deg: float, elevation_deg: float, size: int = 560, scale: float = 62.0
) -> NDArray[np.uint8]:
    a, e = np.radians(azimuth_deg), np.radians(elevation_deg)
    yaw = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0], [0, 0, 1]])
    pitch = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    p = (pitch @ (yaw @ mesh.vertices.astype(float).T)).T  # x right, y away from viewer, z up
    tri = p[mesh.faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.linalg.norm(normal, axis=1)[:, None] + 1e-12
    shade = 0.35 + 0.65 * np.abs(normal @ LIGHT)
    img = np.full((size, size, 3), (24, 24, 28), np.uint8)
    zbuf = np.full((size, size), 1e9)
    sx, sy = size / 2 + tri[:, :, 0] * scale, size - 40 - tri[:, :, 2] * scale
    for i in np.argsort(-tri[:, :, 1].mean(1)):  # far to near
        x, y = sx[i], sy[i]
        x0, x1 = int(max(0, x.min())), int(min(size - 1, x.max() + 1))
        y0, y1 = int(max(0, y.min())), int(min(size - 1, y.max() + 1))
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if x1 < x0 or y1 < y0 or abs(d) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
        l1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
        inside = (l0 >= -0.02) & (l1 >= -0.02) & (1 - l0 - l1 >= -0.02)
        depth = l0 * tri[i, 0, 1] + l1 * tri[i, 1, 1] + (1 - l0 - l1) * tri[i, 2, 1]
        win = img[y0 : y1 + 1, x0 : x1 + 1], zbuf[y0 : y1 + 1, x0 : x1 + 1]
        upd = inside & (depth < win[1])
        win[0][upd] = (mesh.colors[i] * shade[i]).astype(np.uint8)
        win[1][upd] = depth[upd]
    return img


def write_png(path: Path, img: NDArray[np.uint8]) -> None:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    lem = load_lem_mesh()
    write_png(
        Path(sys.argv[1]),
        np.hstack([render(lem, az, el) for az, el in ((35, 18), (-125, 18), (90, 0))]),
    )
