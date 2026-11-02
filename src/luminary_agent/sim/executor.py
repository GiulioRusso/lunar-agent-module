"""Capability-aware boundary between policy requests and spacecraft control.

Local manual control and backend procedures share validation, safety arbitration and structured
feedback. The action vocabulary may be wider than the installed backend's capabilities.
"""

from __future__ import annotations

from dataclasses import replace

from luminary_agent.agc.client import AgcClient
from luminary_agent.plant.discretes import Discretes
from luminary_agent.plant.dynamics import Control, PlanarState
from luminary_agent.policies.actions import ACTION_SPECS, ActionAvailability, ActionResult
from luminary_agent.policies.base import Intent, validate_intent
from luminary_agent.sim.loop import Simulation
from luminary_agent.sim.manual_control import ManualController
from luminary_agent.sim.operations import (
    AgcOperations,
    FlightOperations,
    OperationContext,
    OperationResult,
)


class Executor:
    """One per episode. Backends implement AGC/vehicle procedures, not policy reasoning."""

    def __init__(
        self, sim: Simulation, client: AgcClient, operations: FlightOperations | None = None
    ) -> None:
        self.sim = sim
        self.client = client
        self.operations = operations if operations is not None else AgcOperations(client)
        self.discretes = Discretes(lr_position_1=True)
        self.controller = ManualController()
        self.last_result: str | None = None
        self.last_feedback: ActionResult | None = None
        self.policy_targets: tuple[float | None, float, float] = (None, 0.0, 0.0)
        self.safety_active = False

    @property
    def mode(self) -> str:
        return "auto" if self.sim.manual is None else "manual"

    @property
    def context(self) -> OperationContext:
        # Lightweight test adapters may omit clocks/displays; production always supplies both.
        clock = getattr(self.sim, "clock", None)
        t = getattr(self.sim, "t_offset_s", 0.0) + getattr(clock, "sim_time_s", 0.0)
        display = getattr(self.client, "dsky", None)
        return OperationContext(t, self.mode, getattr(display, "program_number", None))

    def availability(self, action: str) -> ActionAvailability:
        if action in {"hold", "take_manual", "command"}:
            ready = action != "command" or self.mode == "manual"
            cap = ActionAvailability(action, True, ready, "" if ready else "take_manual first")
        else:
            cap = self.operations.availability(action, self.context)
        if self.safety_active and action != "hold" and cap.supported:
            return replace(cap, available=False, reason="safety monitor retains control")
        return cap

    @property
    def capabilities(self) -> tuple[ActionAvailability, ...]:
        return tuple(self.availability(action) for action in ACTION_SPECS)

    async def apply(self, intent: Intent, *, safety: bool = False) -> str:
        """Compatibility string API; detailed status is also retained in last_feedback."""
        return (await self.execute(intent, safety=safety)).to_text()

    async def execute(self, intent: Intent, *, safety: bool = False) -> ActionResult:
        before = self.mode
        action = getattr(intent, "kind", "invalid")
        try:
            validate_intent(intent)
        except ValueError as exc:
            outcome = OperationResult("rejected", str(exc))
        else:
            cap = self.availability(intent.kind)
            if not cap.supported:
                outcome = OperationResult("unsupported", cap.reason)
            elif self.safety_active and not safety and intent.kind != "hold":
                outcome = OperationResult("rejected", "safety monitor retains control")
            elif not cap.available and not (safety and intent.kind in {"take_manual", "command"}):
                outcome = OperationResult("rejected", cap.reason)
            else:
                # Backend I/O failures may have partially applied. Never automatically replay them.
                try:
                    outcome = await self._apply(intent)
                except Exception as exc:
                    outcome = OperationResult("failed", f"{type(exc).__name__}: {exc}")
        if not safety and action == "command" and outcome.status == "applied":
            self.policy_targets = (
                self.controller.descent_rate_ms,
                self.controller.horizontal_ms,
                self.controller.cross_ms,
            )
        feedback = ActionResult(
            action, outcome.status, outcome.message, before, self.mode, outcome.effective_params
        )
        self.last_feedback = feedback
        self.last_result = feedback.to_text()
        return feedback

    def _manual_control(self, state: PlanarState) -> Control:
        return self.controller.control_3d(state, self.sim.z_m, self.sim.zdot_ms)

    async def _apply(self, intent: Intent) -> OperationResult:
        if intent.kind == "hold":
            return OperationResult("applied")
        if intent.kind == "take_manual":
            if self.sim.manual is not None:
                return OperationResult("ignored", "already manual")
            switches = replace(self.discretes, auto_throttle=False)
            await self.client.write_channels(switches.channel_words())
            self.discretes = switches
            self.sim.manual = self._manual_control
            return OperationResult("applied", "manual thrust control active (P67 requested)")
        if intent.kind == "command":
            if self.sim.manual is None:
                return OperationResult("rejected", "take_manual first")
            p = intent.params
            note = self.controller.set_targets(
                p.get("descent_rate_ms"), p.get("horizontal_ms", 0.0), p.get("cross_ms", 0.0)
            )
            return OperationResult(
                "applied",
                note,
                (
                    ("descent_rate_ms", self.controller.descent_rate_ms),
                    ("horizontal_ms", self.controller.horizontal_ms),
                    ("cross_ms", self.controller.cross_ms),
                ),
            )
        return await self.operations.execute(intent, self.context)
