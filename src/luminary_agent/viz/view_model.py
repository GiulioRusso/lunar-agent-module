"""What the window shows, as plain data: `ViewFrame`, built from the same records the recorder
writes. Live and replay go through the same `FrameBuilder`, so a replayed episode looks exactly
like the flight did. No pygame here: everything in this module is testable without a display.

Real data: position, altitude, velocities, mass, thrust, pitch, DSKY, alarms, the radar/AGC
altitudes and the policy's latest intent. Derived: downrange error from the target, propellant
(mass minus the dispersed dry mass), throttle (thrust over the engine's maximum).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.propulsion import F_MAX_N
from luminary_agent.plant.surface import MOON_RATE_RAD_S


@dataclass(frozen=True)
class ViewFrame:
    t_s: float
    downrange_m: float  # along-track, relative to the target (past it: positive)
    cross_m: float  # cross-range; the target is at 0
    h_m: float
    vz_ms: float  # vertical, positive up
    vh_ms: float  # horizontal, relative to the rotating surface
    mass_kg: float
    fuel_kg: float
    thrust_n: float
    throttle: float  # 0..1 of maximum thrust
    pitch_deg: float  # thrust axis from local vertical, tilted against the direction of travel
    mode: str  # "auto" | "manual"
    prog: int | None
    verb: int | None
    noun: int | None
    r1: int | None
    r2: int | None
    r3: int | None
    engine_on: bool
    alarms: tuple[int, ...]
    radar_alt_m: float | None
    agc_alt_m: float | None
    intent: str  # the policy's latest intent, e.g. "command {'descent_rate_ms': -1.0}"
    reason: str  # what asked for that decision (sim/events.py) or the monitor's objection
    applied: str
    veto: bool  # the latest decision was a safety-monitor override
    decisions: int  # so far
    vetoes: int  # so far

    @property
    def target_error_m(self) -> float:
        return math.hypot(self.downrange_m, self.cross_m)


def _intent_text(kind: str, params: dict[str, Any]) -> str:
    args = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return f"{kind}({args})" if args else kind


class FrameBuilder:
    """Turns tick and decision records, in time order, into ViewFrames."""

    def __init__(self, site_x_m: float, dry_mass_kg: float) -> None:
        self.site_x_m = site_x_m
        self.dry_mass_kg = dry_mass_kg
        self._intent = self._reason = self._applied = ""
        self._veto = False
        self._alarms: tuple[int, ...] = ()
        self._radar: float | None = None
        self._agc: float | None = None
        self._decisions = self._vetoes = 0

    def decision(self, record: dict[str, Any]) -> None:
        """A decision record as the recorder writes it (`obs`, `intent`, `applied`, ...)."""
        obs = record["obs"]
        self._intent = _intent_text(record["intent"]["kind"], record["intent"]["params"])
        self._reason, self._applied = record.get("reason", ""), record["applied"]
        self._veto = bool(record.get("veto"))
        self._alarms = tuple(obs["alarms"])
        self._radar, self._agc = obs.get("radar_altitude_m"), obs.get("agc_altitude_m")
        self._decisions += 1
        self._vetoes += self._veto

    def tick(self, tick: dict[str, Any]) -> ViewFrame:
        d = tick["dsky"]
        return ViewFrame(
            t_s=tick["t"],
            downrange_m=tick["x_m"] - self.site_x_m,
            cross_m=tick["z_m"],
            h_m=tick["h_m"],
            vz_ms=tick["hdot_ms"],
            vh_ms=tick["vt_ms"] - MOON_RATE_RAD_S * (R_MOON + tick["h_m"]),
            mass_kg=tick["mass_kg"],
            fuel_kg=max(0.0, tick["mass_kg"] - self.dry_mass_kg),
            thrust_n=tick["thrust_n"],
            throttle=min(1.0, max(0.0, tick["thrust_n"] / F_MAX_N)),
            pitch_deg=tick["pitch_deg"],
            mode=tick.get("mode", "auto"),
            prog=d["prog"], verb=d["verb"], noun=d["noun"], r1=d["r1"], r2=d["r2"], r3=d["r3"],
            engine_on=bool(tick.get("engine_on")),
            alarms=self._alarms,
            radar_alt_m=self._radar,
            agc_alt_m=self._agc,
            intent=self._intent, reason=self._reason, applied=self._applied, veto=self._veto,
            decisions=self._decisions, vetoes=self._vetoes,
        )  # fmt: skip
