"""Executor: turns an agent's Intent into actions on the AGC and the plant, and says what happened.

Intents (policies/base.py): hold; take_manual (clear the auto-throttle discrete -- Luminary's R13
monitor selects P67 and stops commanding the engine -- and hand throttle/attitude to the
ManualController; irreversible, as ROD/P66 is not available); command (targets for the
ManualController). Anything else, or a command before takeover, is rejected, never guessed at.
"""

from __future__ import annotations

from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.plant.discretes import Discretes
from luminary_agent.policies.base import Intent
from luminary_agent.sim.loop import Simulation
from luminary_agent.sim.manual_control import ManualController


class Executor:
    def __init__(self, sim: Simulation, client: AgcClient) -> None:
        self.sim = sim
        self.client = client
        self.controller = ManualController()

    @property
    def mode(self) -> str:
        return "auto" if self.sim.manual is None else "manual"

    async def apply(self, intent: Intent) -> str:
        if intent.kind == "hold":
            return "ok"
        if intent.kind == "take_manual":
            if self.sim.manual is not None:
                return "ignored: already manual"
            await self.client.write_channels(
                Discretes(lr_position_1=True, auto_throttle=False).channel_words()
            )
            self.sim.manual = self.controller.control
            return "ok: manual throttle discrete set (P67 requested)"
        if intent.kind == "command":
            if self.sim.manual is None:
                return "rejected: take_manual first"
            p: dict[str, Any] = intent.params
            note = self.controller.set_targets(
                p.get("descent_rate_ms"), p.get("horizontal_ms", 0.0)
            )
            return "ok" + (f" ({note})" if note else "")
        return f"rejected: unknown intent {intent.kind!r}"
