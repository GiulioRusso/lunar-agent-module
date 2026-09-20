"""What an agent is allowed to see: the DSKY as the crew sees it, the alarms Luminary has raised,
and radar-like truth about the vehicle. Never the plant's internals or the AGC's memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Observation:
    t_s: float
    mode: str  # "auto" (Luminary flies) | "manual" (crew has throttle and attitude)
    program: int | None
    verb: int | None
    noun: int | None
    r1: int | None
    r2: int | None
    r3: int | None
    alarms: tuple[int, ...]  # program alarm codes raised so far (octal digits as an int)
    altitude_m: float  # radar altitude, above the surface
    vertical_ms: float  # positive up
    horizontal_ms: float  # velocity relative to the rotating surface, positive downrange
    thrust_n: float
    mass_kg: float
    propellant_kg: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_text(self) -> str:
        alarms = ",".join(f"{a:o}" for a in self.alarms) or "none"
        return (
            f"t={self.t_s:.0f}s mode={self.mode} P{self.program} V{self.verb} N{self.noun} "
            f"R1={self.r1} R2={self.r2} R3={self.r3} alarms={alarms}\n"
            f"alt={self.altitude_m:.1f}m vz={self.vertical_ms:+.2f}m/s "
            f"vh={self.horizontal_ms:+.2f}m/s thrust={self.thrust_n:.0f}N "
            f"mass={self.mass_kg:.0f}kg propellant={self.propellant_kg:.0f}kg"
        )
