"""Episode log -> one self-contained HTML replay (side elevation + instrument readouts).

Playback of the recorded log only: no AGC, no physics. Usage:
    python -m luminary_agent.viz.replay episode.jsonl.gz out.html [--hz 10]

The terrain is cosmetic (a fixed synthetic profile so height above ground is visible); the
ground the plant actually uses is the altitude-0 line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from luminary_agent.sim.recorder import read_episode

FIELDS = ("t", "h_m", "x_m", "z_m", "hdot_ms", "vt_ms", "mass_kg", "thrust_n", "pitch_deg")

PAGE = (Path(__file__).parent / "replay.html").read_text()


def build(episode: Path, out: Path, hz: float = 10.0) -> None:
    header, ticks = read_episode(episode)
    rows = [[t.get(f) or 0.0 for f in FIELDS] for t in ticks]
    dt = rows[1][0] - rows[0][0]
    stride = max(1, round(1.0 / (hz * dt)))
    data = [[round(v, 3) for v in r] for r in rows[::stride]]
    title = " | ".join(
        f"{k}={v}" for k, v in header.items() if k in ("scenario", "clock", "pointing")
    )
    page = (
        PAGE.replace("__TITLE__", title or "episode")
        .replace("__FIELDS__", json.dumps(list(FIELDS)))
        .replace("__DATA__", json.dumps(data, separators=(",", ":")))
        .replace("__HZ__", str(1.0 / (stride * dt)))
    )
    out.write_text(page)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--hz", type=float, default=10.0)
    a = ap.parse_args()
    build(a.episode, a.out, a.hz)
