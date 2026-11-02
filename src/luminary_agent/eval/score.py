"""Landing judgement. Two separate questions (CODE_REVIEW.md Sec.1.4):

`soft_touchdown`  contact, vertical <= 3.0 m/s, horizontal <= 1.2 m/s (relative to the surface),
                  propellant left.
`mission_success` soft touchdown AND within 100 m of the target AND hazard-free AND slope <= limit.
                  Needs a `Surface`; without one it is "not_scored", never a guess.

Why two? A gentle landing in a crater is soft but not a success; a landing on target at 5 m/s
is on target but not soft. Keeping them apart shows *which* part a policy gets wrong.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from luminary_agent.plant.terrain import Surface
from luminary_agent.scenarios.dispersions import NOMINAL_DRY_MASS_KG
from luminary_agent.sim.descent import DescentResult

MAX_VERTICAL_MS = 3.0
MAX_HORIZONTAL_MS = 1.2
MissionSuccess = bool | Literal["not_scored"]  # True, False, or the string "not_scored"


@dataclass(frozen=True)
class Score:
    """The verdict of one episode (written to the result JSON and the log's last line)."""

    landed: bool
    soft_touchdown: bool
    mission_success: MissionSuccess
    vertical_ms: float
    horizontal_ms: float
    target_error_m: float
    fuel_kg: float
    # The surface verdict behind `mission_success`; None when no surface was scored.
    target_ok: bool | None = None
    hazard_free: bool | None = None
    slope_ok: bool | None = None
    slope_deg: float | None = None
    hazard: str | None = None  # kind of the hazard the footprint overlaps, if any

    def as_dict(self) -> dict[str, float | bool | str | None]:
        return dict(self.__dict__)


def score(
    result: DescentResult,
    dry_mass_kg: float = NOMINAL_DRY_MASS_KG,
    surface: Surface | None = None,
) -> Score:
    """Judge a finished descent (see the module docstring for the two criteria)."""
    landed = result.outcome == "touchdown"
    v = abs(result.vertical_ms)
    hz = math.hypot(result.horizontal_relative_ms, result.lateral_velocity_ms)
    fuel_kg = max(0.0, result.state.mass_kg - dry_mass_kg)
    x_m, z_m = result.downrange_error_m, result.lateral_m
    target_error_m = math.hypot(x_m, z_m)
    soft = landed and v <= MAX_VERTICAL_MS and hz <= MAX_HORIZONTAL_MS and fuel_kg > 0.0
    if surface is None:
        return Score(landed, soft, "not_scored", v, hz, target_error_m, fuel_kg)
    a = surface.assess(x_m, z_m)
    return Score(
        landed, soft, soft and a.target_ok and a.hazard_free and a.slope_ok,
        v, hz, target_error_m, fuel_kg,
        a.target_ok, a.hazard_free, a.slope_ok, round(a.slope_deg, 2),
        None if a.hazard is None else a.hazard.kind,
    )  # fmt: skip
