"""Bounded calls to the synchronous Policy protocol, independent of the model framework.

A daemon worker receives only an immutable observation. On timeout the caller quarantines
that policy for the rest of the episode. Python cannot kill a thread: policies must not
mutate the spacecraft; mutations belong exclusively to the executor. A timed-out model request
may still complete, but its result cannot reach the executor.
"""

from __future__ import annotations

import asyncio
import threading

from luminary_agent.policies.base import Intent, Policy
from luminary_agent.sim.observation import Observation


class DecisionRunner:
    def __init__(self, policy: Policy, timeout_s: float = 30.0) -> None:
        self.policy = policy
        self.timeout_s = timeout_s
        self.disabled = False
        self.failures = 0
        self._reset_pending = True

    async def decide(self, obs: Observation) -> Intent:
        if self.disabled:
            raise RuntimeError("policy disabled after an earlier failure")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[Intent] = loop.create_future()

        def finish(value: Intent | None, error: Exception | None) -> None:
            if result.done():
                return
            if error is not None:
                result.set_exception(error)
            else:
                if value is None:
                    result.set_exception(ValueError("policy returned no intent"))
                else:
                    result.set_result(value)

        def work() -> None:
            value, error = None, None
            try:
                if self._reset_pending:
                    self.policy.reset()
                    self._reset_pending = False
                value = self.policy.decide(obs, obs.t_s)
            except Exception as exc:
                error = exc
            try:
                loop.call_soon_threadsafe(finish, value, error)
            except RuntimeError:
                pass  # episode already closed after a timeout

        threading.Thread(target=work, name="policy-decision", daemon=True).start()
        return await asyncio.wait_for(result, timeout=self.timeout_s)
