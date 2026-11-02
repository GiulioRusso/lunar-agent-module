"""Action vocabulary and observable results, independent of any agent framework.

Recognized is not the same as supported: a valid P66 or abort request can be explicitly
unsupported by the current vehicle backend. Policies discover support in each observation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from luminary_agent.agc.dsky import KEYCODE

ActionStatus = Literal["applied", "submitted", "rejected", "unsupported", "ignored", "failed"]
ParameterValue = float | int | str | None


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: Literal["number", "integer", "choice"] = "number"
    required: bool = False
    nullable: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def validate(self, value: Any) -> None:
        if value is None and self.nullable:
            return
        if self.kind == "choice":
            if not isinstance(value, str) or value not in self.choices:
                raise ValueError(f"{self.name} must be one of {self.choices}")
            return
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        try:
            finite = numeric and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{self.name} must be a finite number")
        if self.kind == "integer" and not isinstance(value, int):
            raise ValueError(f"{self.name} must be an integer")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.name} must be >= {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.name} must be <= {self.maximum}")


@dataclass(frozen=True)
class ActionSpec:
    description: str
    parameters: tuple[Parameter, ...] = ()

    def validate(self, params: dict[str, Any]) -> None:
        fields = {p.name: p for p in self.parameters}
        if set(params) - fields.keys():
            raise ValueError("unexpected intent parameters")
        for name, field in fields.items():
            if name not in params:
                if field.required:
                    raise ValueError(f"missing required parameter {name}")
            else:
                field.validate(params[name])


ACTION_SPECS = {
    "hold": ActionSpec("Keep current authority and targets."),
    "take_manual": ActionSpec(
        "Transfer simulated thrust control to the crew controller; request P67."
    ),
    "command": ActionSpec(
        "Set manual descent, along-track and cross-range velocity targets.",
        (
            Parameter("descent_rate_ms", nullable=True),
            Parameter("horizontal_ms"),
            Parameter("cross_ms"),
        ),
    ),
    "return_auto": ActionSpec(
        "Request a validated handback to AGC control; P67 hands back to P66."
    ),
    "select_p66": ActionSpec(
        "Select AGC rate-of-descent control through a validated mode transition."
    ),
    "adjust_rod": ActionSpec(
        "Send signed ROD switch clicks while P66 is active.",
        (Parameter("clicks", "integer", required=True, minimum=-10, maximum=10),),
    ),
    "redesignate": ActionSpec(
        "Shift the AGC landing aim point by metres from its current aim point.",
        (
            Parameter("downrange_m", required=True, minimum=-1000, maximum=1000),
            Parameter("cross_m", required=True, minimum=-1000, maximum=1000),
        ),
    ),
    "abort": ActionSpec(
        "Request a descent-stage or ascent-stage abort maneuver.",
        (Parameter("stage", "choice", required=True, choices=("descent", "ascent")),),
    ),
    "dsky_key": ActionSpec(
        "Deliver one keyboard key; delivery does not confirm program acceptance.",
        (Parameter("key", "choice", required=True, choices=tuple(KEYCODE)),),
    ),
}


@dataclass(frozen=True)
class ActionAvailability:
    action: str
    supported: bool
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class ActionResult:
    action: str
    status: ActionStatus
    message: str
    mode_before: str
    mode_after: str
    effective_params: tuple[tuple[str, ParameterValue], ...] = ()

    def to_text(self) -> str:
        prefix = "ok" if self.status == "applied" else self.status
        return prefix + (f": {self.message}" if self.message else "")
