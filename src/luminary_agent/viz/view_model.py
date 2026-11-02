"""What the window shows, as plain data: `ViewFrame`, built from the same records the recorder
writes. Live and replay go through the same `FrameBuilder`, so a replayed episode looks exactly
like the flight did. No pygame here: everything in this module is testable without a display.

Real data: position, altitude, velocities, mass, thrust, pitch, DSKY, alarms, the radar/AGC
altitudes and the policy's latest intent. Derived: downrange error from the target, propellant
(mass minus the dispersed dry mass), throttle (thrust over the engine's maximum).

Why a "view model": the renderer only ever sees ViewFrame objects, so it does not care whether
they came from a live run or a log file, and tests can build frames without opening a window.
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
    """Everything drawn for one instant."""

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

    decision_t_s: float | None = None
    decision_latency_s: float = 0.0
    decision_valid_until_s: float | None = None
    rationale: str = ""
    decision_source: str = "policy"
    instrument_model: str = "legacy / unspecified"
    cross_velocity_ms: float = 0.0
    available_actions: tuple[str, ...] = ()
    action_status: str = ""

    agent_stage: str = ""
    agent_model: str = ""
    agent_summary: str = ""
    agent_calls: int = 0
    agent_tokens: int = 0
    agent_evidence: tuple[str, ...] = ()
    agent_risks: tuple[str, ...] = ()
    agent_plan: str = ""
    agent_path: tuple[str, ...] = ()
    decision_history: tuple[str, ...] = ()
    decision_observation: tuple[str, ...] = ()

    @property
    def target_error_m(self) -> float:
        """Straight-line distance from the target."""
        return math.hypot(self.downrange_m, self.cross_m)


def _intent_text(kind: str, params: dict[str, Any]) -> str:
    """e.g. ("command", {"descent_rate_ms": -1.0}) -> "command(descent_rate_ms=-1.0)"."""
    args = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return f"{kind}({args})" if args else kind


class FrameBuilder:
    """Turns tick and decision records, in time order, into ViewFrames."""

    def __init__(self, site_x_m: float, dry_mass_kg: float) -> None:
        self.site_x_m = site_x_m
        self.dry_mass_kg = dry_mass_kg
        # "Sticky" state from the latest decision, copied into every frame after it.
        self._intent = self._reason = self._applied = ""
        self._veto = False
        self._alarms: tuple[int, ...] = ()
        self._radar: float | None = None
        self._agc: float | None = None
        self._decisions = self._vetoes = 0
        self._decision_t: float | None = None
        self._latency = 0.0
        self._valid_until: float | None = None
        self._rationale = ""
        self._source = "policy"
        self._instrument_model = "legacy / unspecified"
        self._available_actions: tuple[str, ...] = ()
        self._action_status = ""
        self._agent: dict[str, Any] = {}
        self._history: list[str] = []
        self._observation: tuple[str, ...] = ()

    def agent_status(self, record: dict[str, Any]) -> None:
        """Progress arrives while simulated time is paused for model inference."""
        for key in ("stage", "model", "summary", "calls", "tokens"):
            if key in record:
                self._agent[key] = record[key]

    def decision(self, record: dict[str, Any]) -> None:
        """A decision record as the recorder writes it (`obs`, `intent`, `applied`, ...)."""
        obs = record["obs"]

        def reading(key: str) -> str:
            value = obs.get(key)
            return f"{value:.2f}" if isinstance(value, (int, float)) else "--"

        self._observation = (
            f"Radar {reading('radar_altitude_m')} m / AGC {reading('agc_altitude_m')} m",
            f"Vz {reading('vertical_ms')} / along {reading('horizontal_ms')} / "
            f"cross {reading('cross_velocity_ms')} m/s",
            f"Fuel {reading('propellant_kg')} kg / target offset "
            f"({reading('target_downrange_m')}, {reading('target_cross_m')}) m",
        )
        self._intent = _intent_text(record["intent"]["kind"], record["intent"]["params"])
        self._reason, self._applied = record.get("reason", ""), record["applied"]
        self._veto = bool(record.get("veto"))
        self._alarms = tuple(obs["alarms"])
        self._radar, self._agc = obs.get("radar_altitude_m"), obs.get("agc_altitude_m")
        self._decision_t = record.get("t")
        self._latency = record.get("latency_s", 0.0)
        self._valid_until = record["intent"].get("valid_until_s")
        self._rationale = record.get("rationale", "")
        self._source = record.get("source", "safety" if self._veto else "policy")
        self._instrument_model = obs.get("instrument_model", "legacy / unspecified")
        self._available_actions = tuple(
            c["action"] for c in obs.get("action_capabilities", ()) if c["available"]
        )
        self._action_status = (record.get("execution") or {}).get("status", "")
        self._decisions += self._source in {"policy", "fallback"}
        self._vetoes += self._veto
        details = record.get("agent") or {}
        self._agent.update(details)
        self._agent.update(
            stage="safety"
            if self._veto
            else ("fallback" if self._source == "fallback" else self._action_status or "executed"),
            summary=self._rationale,
            evidence=details.get("evidence", ()),
            risks=details.get("risks", ()),
            plan=details.get("plan", ""),
            path=details.get("path", ()),
        )
        self._history.append(
            f"{self._decision_t or 0:.1f}s [{self._source}] {self._intent} -> {self._applied}"
        )
        self._history = self._history[-12:]

    def tick(self, tick: dict[str, Any]) -> ViewFrame:
        """A tick record (see sim/loop.py:_record) -> ViewFrame, plus the sticky decision state."""
        d = tick["dsky"]
        return ViewFrame(
            t_s=tick["t"],
            downrange_m=(tick["target_downrange_m"] if tick.get("target_downrange_m") is not None
                         else tick["x_m"] - self.site_x_m),
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
            decision_t_s=self._decision_t, decision_latency_s=self._latency,
            decision_valid_until_s=self._valid_until, rationale=self._rationale,
            decision_source=self._source, instrument_model=self._instrument_model,
            cross_velocity_ms=tick.get("zdot_ms", 0.0),
            available_actions=self._available_actions, action_status=self._action_status,
            agent_stage=self._agent.get("stage", ""), agent_model=self._agent.get("model", ""),
            agent_summary=self._agent.get("summary", ""), agent_calls=self._agent.get("calls", 0),
            agent_tokens=self._agent.get("tokens", 0),
            agent_evidence=tuple(self._agent.get("evidence", ())),
            agent_risks=tuple(self._agent.get("risks", ())),
            agent_plan=self._agent.get("plan", ""), agent_path=tuple(self._agent.get("path", ())),
            decision_history=tuple(self._history), decision_observation=self._observation,
        )  # fmt: skip
