"""The Agent protocol every policy (null, scripted, PID, LLM) implements.

Defined now, in Track A, so the LLM policy (Track B) plugs into a fixed interface
instead of reshaping the codebase later. See APOLLO_AGENT_PLAN.md §1, A8.
"""

from __future__ import annotations

from typing import Any, Protocol

from luminary_agent.sim.observation import Observation


class Intent:
    """A decision handed to the deterministic executor: a command plus how long it stays valid.

    hold() is a first-class intent -- "do nothing" must be an explicit, loggable decision,
    not the absence of one.
    """

    __slots__ = ("kind", "params", "valid_until_s")

    def __init__(self, kind: str, params: dict[str, Any], valid_until_s: float) -> None:
        self.kind = kind
        self.params = params
        self.valid_until_s = valid_until_s


def hold(valid_until_s: float) -> Intent:
    return Intent(kind="hold", params={}, valid_until_s=valid_until_s)


def take_manual(valid_until_s: float) -> Intent:
    """Take manual throttle and attitude from Luminary (irreversible)."""
    return Intent(kind="take_manual", params={}, valid_until_s=valid_until_s)


def command(
    valid_until_s: float, descent_rate_ms: float | None = None, horizontal_ms: float = 0.0
) -> Intent:
    """In manual mode: target vertical rate (m/s, negative = down; None = altitude schedule) and
    horizontal velocity relative to the surface (m/s)."""
    params = {"descent_rate_ms": descent_rate_ms, "horizontal_ms": horizontal_ms}
    return Intent(kind="command", params=params, valid_until_s=valid_until_s)


class Policy(Protocol):
    """One fixed interface. Swapping policies is a config line (§6).

    `decide` is called on a cadence while the whole simulation (plant and AGC) is paused, so a slow
    policy (an LLM) costs wall time, not simulated time.
    """

    name: str

    def decide(self, obs: Observation, t_s: float) -> Intent:
        """Given the current flight state at simulation time t_s, return an Intent.

        Implementations: NullAgent (no intent, pure Luminary), ScriptedAgent (Apollo 11
        timeline), PIDAgent (ROD channel), LLMAgent (planner/executor, Phase 4).
        """
        ...

    def reset(self) -> None:
        """Called once per episode before the first decide()."""
        ...
