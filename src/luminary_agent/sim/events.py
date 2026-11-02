"""When the policy is consulted: on events, not on a fixed cadence.

A 0.5 s cadence is ~1,600 decisions in a 800 s descent. A scripted policy does not care; an LLM
at ~2 s per decision would add an hour of wall clock to a 20-minute episode, which is the whole
difference between a 60-episode eval that finishes and one that does not. So the planner fires on
what actually changes a decision -- a program transition, a new alarm, radar lock coming or going,
the mode changing, the previous intent expiring -- plus a slow heartbeat so "nothing happened" is
still revisited (CODE_REVIEW.md Phase 4, item 2).

`MIN_PERIOD_S` is a floor, not a schedule: two events in the same instant cost one decision.

Usage in the loop:  `why = trigger.reason(obs)`; if not None -> ask the policy ->
`trigger.fired(obs, intent.valid_until_s)`.
"""

from __future__ import annotations

from luminary_agent.sim.observation import Observation

HEARTBEAT_S = 5.0  # ask at least this often, even if nothing changed
MIN_PERIOD_S = 0.5  # never ask more often than this


class Trigger:
    """Decides whether this tick deserves a decision, and says why (the reason is logged: a
    decision whose cause is unknown cannot be analysed afterwards)."""

    def __init__(self, heartbeat_s: float = HEARTBEAT_S, min_period_s: float = MIN_PERIOD_S):
        self.heartbeat_s = heartbeat_s
        self.min_period_s = min_period_s
        self.prev: Observation | None = None  # the observation at the last decision
        self.last_s = float("-inf")  # -inf: "never" (any time is later)
        self.valid_until_s = float("-inf")

    def reason(self, obs: Observation) -> str | None:
        """None: no decision needed this tick. Otherwise a short description of what changed."""
        if obs.t_s - self.last_s < self.min_period_s:
            return None
        # Checked in priority order; the first change found is the reason reported.
        p = self.prev
        if p is None:
            return "first"
        if obs.program != p.program:
            return f"program {p.program}->{obs.program}"
        if len(obs.alarms) > len(p.alarms):
            return "alarm " + ",".join(f"{a:o}" for a in obs.alarms[len(p.alarms) :])
        if obs.mode != p.mode:
            return f"mode {p.mode}->{obs.mode}"
        if (obs.radar_altitude_m is None) != (p.radar_altitude_m is None):
            return "radar lock lost" if obs.radar_altitude_m is None else "radar lock regained"
        if obs.t_s >= self.valid_until_s:
            return "intent expired"
        if obs.t_s - self.last_s >= self.heartbeat_s:
            return "heartbeat"
        return None

    def fired(self, obs: Observation, valid_until_s: float) -> None:
        """Record that a decision was taken at `obs`, valid until `valid_until_s`."""
        self.prev = obs
        self.last_s = obs.t_s
        self.valid_until_s = max(valid_until_s, obs.t_s + self.min_period_s)
