"""Episode log -> frames for the native window. Playback of the recorded log only: no AGC, no
physics, no model, no network. The log is read once, streaming; frames are thinned to `hz` of
simulated time (the recorder keeps every tick; the window does not need 50 a second).

    from luminary_agent.viz.replay import load_episode
    episode = load_episode(Path("results/runs/t3_s0_scripted.jsonl.gz"))

CLI: `luminary view results/runs/t3_s0_scripted.jsonl.gz [--hz 10] [--screenshot out.png]`.
"""

from __future__ import annotations

import gzip
import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from luminary_agent.plant.terrain import Surface
from luminary_agent.scenarios.dispersions import (
    LOADED_MASS_KG,
    NOMINAL_DRY_MASS_KG,
    NOMINAL_PROPELLANT_KG,
)
from luminary_agent.viz.view_model import FrameBuilder, ViewFrame


def dry_mass_kg(header: dict[str, Any]) -> float:
    """Mass at which the propellant is gone, from the header's dispersion (nominal if absent)."""
    scale = header.get("dispersion", {}).get("propellant_scale")
    return NOMINAL_DRY_MASS_KG if scale is None else LOADED_MASS_KG - NOMINAL_PROPELLANT_KG * scale


def title(header: dict[str, Any]) -> str:
    """Window caption, e.g. 'policy=scripted | tier=3 | seed=0'."""
    return " | ".join(f"{k}={header[k]}" for k in ("policy", "tier", "seed") if k in header)


@dataclass
class Episode:
    """A loaded log: header, thinned frames, and the landing verdict."""

    header: dict[str, Any]
    frames: list[ViewFrame]
    landing: dict[str, Any] | None = None  # the final verdict record, if the run finished
    _times: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """(dataclass hook, runs after __init__) cache frame times for fast lookup."""
        self._times = [f.t_s for f in self.frames]

    @property
    def surface(self) -> Surface | None:
        """The terrain, rebuilt from the header (None if the episode had no surface)."""
        s = self.header.get("surface")
        return None if not s else Surface.from_dict(s)

    @property
    def title(self) -> str:
        return title(self.header)

    def index_at(self, t_s: float) -> int:
        """The last frame at or before `t_s` (the first frame if `t_s` precedes them all)."""
        # bisect = binary search in the sorted list of frame times (O(log n)).
        return max(0, bisect_right(self._times, t_s) - 1)


def load_episode(path: Path, hz: float = 10.0) -> Episode:
    """Read a .jsonl.gz log into an Episode, keeping about `hz` frames per simulated second."""
    header: dict[str, Any] = {}
    builder = FrameBuilder(0.0, NOMINAL_DRY_MASS_KG)
    frames: list[ViewFrame] = []
    landing: dict[str, Any] | None = None
    last_t, last_tick = float("-inf"), None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            kind = r.get("type")
            if kind == "header":
                header = r
                builder = FrameBuilder(header.get("site_x_m", 0.0), dry_mass_kg(header))
            elif kind in {"decision", "agent_status"}:
                if kind == "decision":
                    builder.decision(r)
                else:
                    builder.agent_status(r)
                if last_tick is not None and last_tick["t"] == r["t"]:
                    frame = builder.tick(last_tick)
                    if frames and frames[-1].t_s == frame.t_s:
                        frames[-1] = frame
                    else:
                        frames.append(frame)
                    last_t = frame.t_s
            elif kind == "tick":
                last_tick = r
                # Thin: keep a tick only if >= 1/hz simulated seconds after the last kept one.
                if r["t"] - last_t >= 1.0 / hz:
                    frames.append(builder.tick(r))
                    last_t = r["t"]
            elif kind == "landing":
                landing = r
    if not header:
        raise ValueError(f"{path} has no header line")
    if last_tick is not None and (not frames or frames[-1].t_s != last_tick["t"]):
        frames.append(builder.tick(last_tick))  # always end on the final tick
    return Episode(header, frames, landing)
