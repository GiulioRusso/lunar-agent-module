"""Deterministic flight-envelope monitor with veto power over the policy (Phase 4, item 4).

It runs every tick on the same Observation the policy gets, including ideal-state instruments.
When the vehicle leaves the envelope
it overrides whatever the policy last commanded; the agent cannot disable it, and the number of
vetoes per episode is a headline metric, not a footnote.

Two rules, both actionable (a rule that fires when nothing can be done is a log line, not a
safety measure):

  1. **Arrestable descent.** Stopping a descent rate `v` needs `v^2 / 2a` of altitude. The DPS has
     roughly 2 m/s^2 of net deceleration available at landing mass; the monitor reserves half of
     that, so the envelope is `|v_down| <= sqrt(2 * 1.0 * h) + 0.5`. At 2 km that allows 63 m/s
     (a nominal braking phase peaks well inside it); at 10 m it allows 5 m/s; at touchdown it
     allows the 0.5 m/s of margin below the 3 m/s design limit.
  2. **Horizontal speed near the ground.** Below 30 m the LM must be nearly stationary over the
     surface (the design limit is 1.2 m/s, a leg that digs in tips the vehicle over); more than
     3 m/s there is vetoed to a null-out.

The response is always the minimum that restores the envelope: take manual control if Luminary
still has it, then command a safe rate. A veto is re-applied only when its reason changes or it
has been standing for `REPEAT_S`, so a persistent violation is one decision, not fifty a second.

Hysteresis (used below): once a rule has fired, it only clears when the vehicle is comfortably
inside the limit (CLEAR_MARGIN), not the instant it crosses back -- like a thermostat that turns
on at 19 and off at 21 degrees, to avoid flicking on and off around one threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from luminary_agent.policies.base import Intent, command, take_manual
from luminary_agent.sim.observation import Observation

RESERVE_DECEL_MS2 = 1.0  # half the DPS's net deceleration at landing mass
TOUCHDOWN_MARGIN_MS = 0.5
LANDING_FLOOR_MS = 2.5  # below this nothing is vetoed: it lands inside the 3.0 m/s design limit
NEAR_GROUND_M = 30.0
MAX_NEAR_GROUND_HORIZONTAL_MS = 3.0
SAFE_DESCENT_RATE_MS = -1.0  # what a veto commands once manual
REPEAT_S = 5.0
CLEAR_MARGIN = 0.75  # a standing rule only clears once well inside its limit


def max_descent_rate_ms(h_m: float) -> float:
    """The fastest descent (m/s, positive) still arrestable from altitude `h_m`.

    Floored at `LANDING_FLOOR_MS`: the arrest envelope goes to zero at the ground, but touching
    down at 1 m/s is a *good* landing, so without the floor the monitor vetoes contact itself.
    """
    return max(
        math.sqrt(2.0 * RESERVE_DECEL_MS2 * max(h_m, 0.0)) + TOUCHDOWN_MARGIN_MS, LANDING_FLOOR_MS
    )


@dataclass
class Veto:
    """One override: when, why, and the Intent the executor applies instead of the policy's."""

    t_s: float
    reason: str
    intent: Intent
    release: bool = False  # not a veto: the envelope is back, hand control to the policy's targets


@dataclass
class SafetyMonitor:
    """Stateful monitor for one episode; descent.py calls check(obs) every tick."""

    vetoes: list[Veto] = field(default_factory=list)
    _rule: str | None = None  # which rule is standing, NOT its message: the message carries live
    _last_s: float = float("-inf")  # numbers, so comparing messages never dedupes anything
    _commanded: bool = False

    @property
    def active(self) -> bool:
        """Authority remains latched even when a repeated log entry is suppressed."""
        return self._rule is not None

    def altitude(self, obs: Observation) -> float | None:
        """What the monitor believes the altitude is: the radar, or the AGC when there is no lock.
        With neither, it cannot judge and says so by returning None."""
        return obs.radar_altitude_m if obs.radar_altitude_m is not None else obs.agc_altitude_m

    def violation(self, obs: Observation) -> tuple[str, str] | None:
        """(rule, message) or None. The rule identifies the envelope that is broken and is what
        de-duplicates a standing violation; the message describes this instant.

        A rule that is *already* standing is judged against a looser limit (`CLEAR_MARGIN`), so it
        clears only once the vehicle is well inside. Without that hysteresis a noisy radar
        altitude around the 30 m threshold made the monitor veto and release three times a second
        (seen in a real episode at t=838-839 s).
        """
        h = self.altitude(obs)
        if h is None:
            return None
        standing = self._rule
        # Rule 1: arrestable descent rate (tighter limit to *clear* a standing violation).
        slack = CLEAR_MARGIN if standing == "descent_rate" else 1.0
        limit = max_descent_rate_ms(h) * slack
        if -obs.vertical_ms > limit:
            return (
                "descent_rate",
                f"descent {-obs.vertical_ms:.1f} m/s exceeds {limit:.1f} m/s at {h:.0f} m",
            )
        # Rule 2: horizontal speed near the ground.
        near, fast = NEAR_GROUND_M, MAX_NEAR_GROUND_HORIZONTAL_MS
        if standing == "horizontal":
            near, fast = near / CLEAR_MARGIN, fast * CLEAR_MARGIN
        horizontal = math.hypot(obs.horizontal_ms, obs.cross_velocity_ms)
        if h <= near and horizontal > fast:
            return "horizontal", f"horizontal {horizontal:.1f} m/s at {h:.0f} m"
        return None

    def check(self, obs: Observation) -> Veto | None:
        """The veto to apply this tick, or None. Called every tick, before the policy's intent
        stands."""
        found = self.violation(obs)
        if self.altitude(obs) is None and self.active:
            # Losing both altitude sources is not evidence that the envelope recovered.
            found = (self._rule or "unknown", "altitude unavailable: retain safety control")
        if found is None:
            self._rule = None
            if self._commanded:
                # Inside the envelope again: give the policy's own targets back, otherwise the
                # monitor's safe rate is flown all the way to the ground.
                self._commanded = False
                return Veto(
                    obs.t_s,
                    "envelope restored: back to the policy's targets",
                    command(obs.t_s + REPEAT_S, descent_rate_ms=None),
                    release=True,
                )
            return None
        rule, message = found
        if rule == self._rule and obs.t_s - self._last_s < REPEAT_S:
            return None  # same violation, already acted on recently
        self._rule, self._last_s = rule, obs.t_s
        # Step 1: get control away from Luminary; step 2 (next veto): command a safe rate.
        if obs.mode == "auto":
            intent = take_manual(obs.t_s + REPEAT_S)
        else:
            intent = command(obs.t_s + REPEAT_S, descent_rate_ms=SAFE_DESCENT_RATE_MS)
            self._commanded = True
        veto = Veto(obs.t_s, message, intent)
        self.vetoes.append(veto)
        return veto
