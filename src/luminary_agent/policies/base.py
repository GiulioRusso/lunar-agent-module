"""The Agent protocol every policy (null, scripted, PID, LLM) implements.

The same contract connects deterministic and LangGraph policies to the executor.
See CODE_REVIEW.md for the complete control flow.

To write your own policy: a class with a `name` string, `decide(obs, t_s) -> Intent` and
`reset()`; no inheritance needed (typing.Protocol = "anything with these members fits").
Register it in policies/scripted.py:POLICIES and pass `--policy <name>`. Minimal example:

    class Cautious:
        name = "cautious"
        def reset(self) -> None: pass
        def decide(self, obs, t_s):
            if obs.mode == "auto" and obs.propellant_kg < 300:
                return take_manual(t_s + 1.0)
            return hold(t_s + 1.0)
"""

from __future__ import annotations

from typing import Any, Protocol

from luminary_agent.policies.actions import ACTION_SPECS, Parameter
from luminary_agent.sim.observation import Observation


class Intent:
    """A decision handed to the deterministic executor: a command plus how long it stays valid.

    hold() is a first-class intent -- "do nothing" must be an explicit, loggable decision,
    not the absence of one.
    """

    __slots__ = (
        "kind",
        "params",
        "valid_until_s",
        "rationale",
        "details",
    )  # fixed attribute set (small, no typos)

    def __init__(
        self, kind: str, params: dict[str, Any], valid_until_s: float, rationale: str = ""
    ) -> None:
        self.details: dict[str, Any] = {}
        self.rationale = rationale
        self.kind = kind
        self.params = params
        self.valid_until_s = valid_until_s


def validate_intent(value: object, t_s: float | None = None) -> Intent:
    """Reject malformed actions before mutation; the controller clamps numeric bounds."""
    if not isinstance(value, Intent):
        raise ValueError("expected an Intent")
    if not isinstance(value.kind, str) or value.kind not in ACTION_SPECS:
        raise ValueError("unknown intent kind")
    if not isinstance(value.params, dict):
        raise ValueError("params must be a dictionary")
    ACTION_SPECS[value.kind].validate(value.params)
    deadline = value.valid_until_s
    Parameter("valid_until_s").validate(deadline)
    if t_s is not None and not t_s < deadline <= t_s + 60.0:
        raise ValueError("intent validity must be in (now, now + 60 seconds]")
    if not isinstance(value.rationale, str) or len(value.rationale) > 1000:
        raise ValueError("rationale must be text of at most 1000 characters")
    return value


# Helper constructors: build Intents through these, not Intent(...) directly.
def hold(valid_until_s: float) -> Intent:
    """Do nothing; ask me again at `valid_until_s` at the latest."""
    return Intent(kind="hold", params={}, valid_until_s=valid_until_s)


def take_manual(valid_until_s: float) -> Intent:
    """Take manual throttle and attitude from Luminary (irreversible)."""
    return Intent(kind="take_manual", params={}, valid_until_s=valid_until_s)


def command(
    valid_until_s: float,
    descent_rate_ms: float | None = None,
    horizontal_ms: float = 0.0,
    cross_ms: float = 0.0,
) -> Intent:
    """In manual mode: target vertical rate (m/s, negative = down; None = altitude schedule) and
    horizontal velocity relative to the surface (m/s)."""
    params = {
        "descent_rate_ms": descent_rate_ms,
        "horizontal_ms": horizontal_ms,
        "cross_ms": cross_ms,
    }
    return Intent(kind="command", params=params, valid_until_s=valid_until_s)


def return_auto(valid_until_s: float) -> Intent:
    return Intent("return_auto", {}, valid_until_s)


def select_p66(valid_until_s: float) -> Intent:
    return Intent("select_p66", {}, valid_until_s)


def adjust_rod(valid_until_s: float, clicks: int) -> Intent:
    return Intent("adjust_rod", {"clicks": clicks}, valid_until_s)


def redesignate(valid_until_s: float, downrange_m: float, cross_m: float) -> Intent:
    return Intent("redesignate", {"downrange_m": downrange_m, "cross_m": cross_m}, valid_until_s)


def abort(valid_until_s: float, stage: str = "ascent") -> Intent:
    return Intent("abort", {"stage": stage}, valid_until_s)


def dsky_key(valid_until_s: float, key: str) -> Intent:
    return Intent("dsky_key", {"key": key}, valid_until_s)


class Policy(Protocol):
    """One fixed interface. Swapping policies is a config line (§6).

    `decide` is called on a cadence while the whole simulation (plant and AGC) is paused, so a slow
    policy (an LLM) costs wall time, not simulated time.
    """

    name: str

    def decide(self, obs: Observation, t_s: float) -> Intent:
        """Given what the crew can see at simulation time t_s, return an Intent.

        Implementations: NullAgent (pure Luminary), ScriptedAgent (fixed takeover rule),
        FlightAgent (LangGraph model supervision).
        """
        ...

    def reset(self) -> None:
        """Called once per episode before the first decide()."""
        ...
