"""Backend seam for AGC/vehicle procedures, separate from the policy vocabulary.

Future backends must perform the physical procedure and confirm its observed outcome before
returning 'applied'. Sending a key/discrete alone is only 'submitted'. They must preserve
simulation/AGC lockstep and leave safety and episode termination checks running each tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from luminary_agent.policies.actions import ActionAvailability, ActionStatus, ParameterValue
from luminary_agent.policies.base import Intent


@dataclass(frozen=True)
class OperationContext:
    t_s: float
    mode: str
    program: int | None


@dataclass(frozen=True)
class OperationResult:
    status: ActionStatus
    message: str = ""
    effective_params: tuple[tuple[str, ParameterValue], ...] = ()


class FlightOperations(Protocol):
    """Implement procedures and their prerequisites together; no optimistic mode switches."""

    def availability(self, action: str, context: OperationContext) -> ActionAvailability: ...
    async def execute(self, intent: Intent, context: OperationContext) -> OperationResult: ...


class KeyboardPort(Protocol):
    async def press_key(self, key: str) -> None: ...


UNSUPPORTED = {
    "return_auto": (
        "P67 hands back to P66; validated P66 loads and actuator synchronization are missing"
    ),
    "select_p66": "P66 requires validated pad loads and a verified mode-transition backend",
    "adjust_rod": "ROD clicks require a MARKRUPT input path and a validated P66 controller",
    "redesignate": "LPD redesignation requires MARKRUPT and a verified AGC aim-point update",
    "abort": "abort requires stage/engine dynamics, abort guidance coupling and abort scoring",
}
KEY_INTERVAL_S = 0.12


class AgcOperations:
    """Current backend: keyboard delivery, explicit capability failures for missing procedures."""

    def __init__(self, keyboard: KeyboardPort) -> None:
        self.keyboard = keyboard
        self._next_key_s = float("-inf")

    def availability(self, action: str, context: OperationContext) -> ActionAvailability:
        if action == "dsky_key":
            ready = context.t_s >= self._next_key_s
            return ActionAvailability(
                action, True, ready, "" if ready else "wait for the previous key to be consumed"
            )
        return ActionAvailability(
            action, False, False, UNSUPPORTED.get(action, "no procedure backend installed")
        )

    async def execute(self, intent: Intent, context: OperationContext) -> OperationResult:
        capability = self.availability(intent.kind, context)
        if not capability.supported:
            return OperationResult("unsupported", capability.reason)
        if not capability.available:
            return OperationResult("rejected", capability.reason)
        key = intent.params["key"]
        # No AGC-only stepping here. The next ordinary simulation tick consumes the key.
        await self.keyboard.press_key(key)
        self._next_key_s = context.t_s + KEY_INTERVAL_S
        return OperationResult(
            "submitted", f"DSKY {key} sent; inspect subsequent display feedback", (("key", key),)
        )
