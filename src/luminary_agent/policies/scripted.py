"""The two non-learning baselines: pure Luminary, and Luminary plus a fixed crew takeover rule.

POLICIES maps the `--policy` command-line name to the class; the runners instantiate it.
"""

from __future__ import annotations

from collections.abc import Callable

from luminary_agent.policies.base import Intent, Policy, hold, take_manual
from luminary_agent.sim.observation import Observation


class NullAgent:
    """Does nothing: the reference trajectory of unassisted Luminary."""

    name = "null"

    def decide(self, obs: Observation, t_s: float) -> Intent:
        intent = hold(t_s + 5.0)
        intent.rationale = "Null policy: leave guidance and control to Luminary."
        return intent

    def reset(self) -> None:
        pass


class ScriptedAgent:
    """Takes manual control below `takeover_h_m` or when Luminary reaches P65, then leaves the
    ManualController on its altitude schedule."""

    name = "scripted"

    def __init__(self, takeover_h_m: float = 150.0) -> None:
        self.takeover_h_m = takeover_h_m

    def decide(self, obs: Observation, t_s: float) -> Intent:
        # Low on radar (None = no lock, so not "low") or Luminary already in final descent.
        radar_low = obs.radar_altitude_m is not None and obs.radar_altitude_m <= self.takeover_h_m
        if obs.mode == "auto" and (radar_low or obs.program == 65):
            intent = take_manual(t_s + 1.0)
            intent.rationale = (
                "Takeover threshold reached: low radar altitude or P65 final descent."
            )
            return intent
        intent = hold(t_s + 1.0)
        intent.rationale = (
            "Manual controller follows the descent schedule and nulls both horizontal speeds."
            if obs.mode == "manual"
            else "Above takeover threshold; continue AGC guidance."
        )
        return intent

    def reset(self) -> None:
        pass


# Registry: add a new policy class here to make it selectable from the command line.
def llm_policy() -> Policy:
    try:
        from luminary_agent.policies.agent import FlightAgent
    except ImportError as exc:
        raise RuntimeError("Install agent dependencies with: uv sync --extra agent") from exc
    return FlightAgent()


POLICIES: dict[str, Callable[[], Policy]] = {
    "null": NullAgent,
    "scripted": ScriptedAgent,
    "llm": llm_policy,
}
