"""The two non-learning baselines: pure Luminary, and Luminary plus a fixed crew takeover rule."""

from __future__ import annotations

from luminary_agent.policies.base import Intent, hold, take_manual
from luminary_agent.sim.observation import Observation


class NullAgent:
    """Does nothing: the reference trajectory of unassisted Luminary."""

    name = "null"

    def decide(self, obs: Observation, t_s: float) -> Intent:
        return hold(t_s + 1.0)

    def reset(self) -> None:
        pass


class ScriptedAgent:
    """Takes manual control below `takeover_h_m` or when Luminary reaches P65, then leaves the
    ManualController on its altitude schedule."""

    name = "scripted"

    def __init__(self, takeover_h_m: float = 150.0) -> None:
        self.takeover_h_m = takeover_h_m

    def decide(self, obs: Observation, t_s: float) -> Intent:
        if obs.mode == "auto" and (obs.altitude_m <= self.takeover_h_m or obs.program == 65):
            return take_manual(t_s + 1.0)
        return hold(t_s + 1.0)

    def reset(self) -> None:
        pass


POLICIES = {"null": NullAgent, "scripted": ScriptedAgent}
