"""Landing judgement. Two separate questions (APOLLO_AGENT_PLAN.md Sec.1.4):

`soft_touchdown`  contact, vertical <= 3.0 m/s, horizontal <= 1.2 m/s (relative to the surface),
                  propellant left.
`mission_success` soft touchdown AND within 100 m of the target AND hazard-free AND slope <= limit.
                  Needs a `Surface`; without one it is "not_scored", never a guess.
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
MissionSuccess = bool | Literal["not_scored"]


@dataclass(frozen=True)
class Score:
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
    landed = result.outcome == "touchdown"
    v, hz = abs(result.vertical_ms), abs(result.horizontal_relative_ms)
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
