"""Landing scorer: a run is judged only from the plant's final state, never the AGC's opinion."""

from __future__ import annotations

from dataclasses import dataclass

from luminary_agent.sim.descent import DescentResult

MAX_VERTICAL_MS = 3.0
MAX_HORIZONTAL_MS = 1.2


@dataclass(frozen=True)
class Score:
    landed: bool
    safe: bool
    vertical_ms: float
    horizontal_ms: float
    site_error_m: float
    fuel_kg: float

    def as_dict(self) -> dict[str, float | bool]:
        return dict(self.__dict__)


def score(result: DescentResult, dry_mass_kg: float = 6_800.0) -> Score:
    landed = result.outcome == "touchdown"
    v, hz = abs(result.vertical_ms), abs(result.horizontal_relative_ms)
    return Score(
        landed,
        landed and v <= MAX_VERTICAL_MS and hz <= MAX_HORIZONTAL_MS,
        v,
        hz,
        abs(result.downrange_error_m),
        max(0.0, result.state.mass_kg - dry_mass_kg),
    )
