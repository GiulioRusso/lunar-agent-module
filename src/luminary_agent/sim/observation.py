"""What an agent is allowed to see: the DSKY as the crew sees it, the alarms Luminary has raised,
radar-like truth about the vehicle, and -- low enough for a crew to see the ground -- where the
target is and what the terrain under and ahead of the LM looks like. Velocities, mass and
visual geometry are ideal truth instruments; radar alone has faults.
The manual controller also uses ideal state. AGC memory is not exposed to the policy.

The surface fields exist because a scenario may only use what the crew can read *and* change: the
target, the slope and the hazards decide `mission_success`, and horizontal velocity commands can
steer the touchdown point, so the agent has to be able to see them.

An Observation is an immutable snapshot built by the simulation loop each tick; the policy's
decide() gets it, the safety monitor gets it, and it is written to the episode log.
to_text() is the compact human/LLM-readable form.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from luminary_agent.plant.terrain import Surface
from luminary_agent.policies.actions import ActionAvailability, ActionResult

TARGET_VISIBLE_M = (
    3_000.0  # [ours] altitude below which the landing point designator shows the target
)
TERRAIN_VISIBLE_M = 500.0  # [ours] altitude below which relief and boulders can be judged by eye
HAZARD_RANGE_M = 250.0  # hazards further than this from the LM are not reported


@dataclass(frozen=True)
class Observation:
    """Everything a policy may know at time t_s. DSKY fields are None when blank."""

    t_s: float
    mode: str  # "auto" (Luminary flies) | "manual" (crew has throttle and attitude)
    program: int | None
    verb: int | None
    noun: int | None
    r1: int | None
    r2: int | None
    r3: int | None
    alarms: tuple[int, ...]  # program alarm codes raised so far (octal digits as an int)
    radar_altitude_m: float | None  # None: no radar lock
    agc_altitude_m: float | None  # Luminary's own altitude on the DSKY (N63/N64 R3), if shown
    vertical_ms: float  # positive up
    horizontal_ms: float  # velocity relative to the rotating surface, positive downrange
    thrust_n: float
    mass_kg: float
    propellant_kg: float
    # The surface, once low enough to see it (None / empty above that). Positions are metres,
    # downrange positive past the target / ahead of the LM, cross-range as in the plant.
    target_downrange_m: float | None = None  # the LM's offset from the target
    target_cross_m: float | None = None
    slope_here_deg: float | None = None  # steepest slope over the footprint under the LM
    hazards_near: tuple[
        tuple[str, float, float, float], ...
    ] = ()  # (kind, dx, dz, radius) from the LM

    instrument_model: str = "ideal_state_with_faulted_radar"
    previous_action: str | None = None
    cross_velocity_ms: float = 0.0
    action_capabilities: tuple[ActionAvailability, ...] = ()
    previous_action_result: ActionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """Plain dict (for JSON logs)."""
        return asdict(self)

    def to_text(self) -> str:
        """Multi-line summary, e.g. "t=412s mode=auto P64 V16 N68 ... radar_alt=1520m ..."."""

        def fmt(v: float | None) -> str:
            return "none" if v is None else f"{v:.0f}m"

        alarms = ",".join(f"{a:o}" for a in self.alarms) or "none"
        return (
            f"instruments={self.instrument_model} "
            f"previous_action={self.previous_action or 'none'}\n"
            f"t={self.t_s:.0f}s mode={self.mode} P{self.program} V{self.verb} N{self.noun} "
            f"R1={self.r1} R2={self.r2} R3={self.r3} alarms={alarms}\n"
            f"radar_alt={fmt(self.radar_altitude_m)} agc_alt={fmt(self.agc_altitude_m)} "
            f"vz={self.vertical_ms:+.2f}m/s "
            f"vh={self.horizontal_ms:+.2f}m/s cross_v={self.cross_velocity_ms:+.2f}m/s "
            f"thrust={self.thrust_n:.0f}N "
            f"mass={self.mass_kg:.0f}kg propellant={self.propellant_kg:.0f}kg"
            + self._surface_text()
            + self._capability_text()
        )

    def _capability_text(self) -> str:
        if not self.action_capabilities:
            return ""
        available = ", ".join(c.action for c in self.action_capabilities if c.available) or "none"
        blocked = "; ".join(
            f"{c.action}: {c.reason}" for c in self.action_capabilities if not c.available
        )
        return f"\nactions available: {available}\nactions unavailable: {blocked}"

    def _surface_text(self) -> str:
        """Extra lines about target/terrain, only once they are visible."""
        if self.target_downrange_m is None:
            return ""
        text = f"\ntarget: {self.target_downrange_m:+.0f}m downrange, "
        text += f"{self.target_cross_m:+.0f}m cross"
        if self.slope_here_deg is not None:
            near = "; ".join(
                f"{k} r={r:.0f}m at ({dx:+.0f},{dz:+.0f})" for k, dx, dz, r in self.hazards_near
            )
            text += f"\nterrain: slope {self.slope_here_deg:.1f}deg, hazards: "
            text += near or "none within 250m"
        return text


def surface_view(
    surface: Surface | None, downrange_m: float, cross_m: float, altitude_m: float
) -> dict[str, Any]:
    """The surface fields of an Observation for a LM at this offset from the target."""
    if surface is None or altitude_m > TARGET_VISIBLE_M:
        return {}
    view: dict[str, Any] = {"target_downrange_m": downrange_m, "target_cross_m": cross_m}
    if altitude_m <= TERRAIN_VISIBLE_M:
        view["slope_here_deg"] = surface.slope_deg(downrange_m, cross_m)
        # Hazards within range, as positions relative to the LM, nearest first.
        view["hazards_near"] = tuple(
            sorted(
                (
                    (h.kind, h.x_m - downrange_m, h.z_m - cross_m, h.radius_m)
                    for h in surface.hazards
                    if math.hypot(h.x_m - downrange_m, h.z_m - cross_m)
                    <= HAZARD_RANGE_M + h.radius_m
                ),
                key=lambda h: math.hypot(h[1], h[2]),
            )
        )
    return view
