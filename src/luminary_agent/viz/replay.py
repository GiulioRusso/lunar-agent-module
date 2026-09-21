"""Episode log -> frames for the native window. Playback of the recorded log only: no AGC, no
physics, no model, no network. The log is read once, streaming; frames are thinned to `hz` of
simulated time (the recorder keeps every tick; the window does not need 50 a second).

    from luminary_agent.viz.replay import load_episode
    episode = load_episode(Path("results/runs/t3_s0_scripted.jsonl.gz"))
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
    return " | ".join(f"{k}={header[k]}" for k in ("policy", "tier", "seed") if k in header)


@dataclass
class Episode:
    header: dict[str, Any]
    frames: list[ViewFrame]
    landing: dict[str, Any] | None = None  # the final verdict record, if the run finished
    _times: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._times = [f.t_s for f in self.frames]

    @property
    def surface(self) -> Surface | None:
        s = self.header.get("surface")
        return None if not s else Surface.from_dict(s)

    @property
    def title(self) -> str:
        return title(self.header)

    def index_at(self, t_s: float) -> int:
        """The last frame at or before `t_s` (the first frame if `t_s` precedes them all)."""
        return max(0, bisect_right(self._times, t_s) - 1)


def load_episode(path: Path, hz: float = 10.0) -> Episode:
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
            elif kind == "decision":
                builder.decision(r)
            elif kind == "tick":
                last_tick = r
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
