"""The decision trigger fires on what changes a decision, and no more often than the floor.

Tests sim/events.py:Trigger. `obs(t, **kw)` builds an Observation at time t, overriding any
field by keyword; `fire` asks the trigger and, if it fires, records the decision like the loop.

Run alone: `uv run pytest tests/unit/test_events.py -v`.
"""

from __future__ import annotations

from luminary_agent.sim.events import HEARTBEAT_S, MIN_PERIOD_S, Trigger
from luminary_agent.sim.observation import Observation


def obs(t: float, **kw: object) -> Observation:
    base: dict[str, object] = dict(
        t_s=t, mode="auto", program=63, verb=6, noun=63, r1=1, r2=2, r3=3, alarms=(),
        radar_altitude_m=1000.0, agc_altitude_m=1010.0, vertical_ms=-20.0, horizontal_ms=100.0,
        thrust_n=40000.0, mass_kg=12000.0, propellant_kg=5000.0,
    )  # fmt: skip
    return Observation(**{**base, **kw})  # type: ignore[arg-type]


def fire(trigger: Trigger, o: Observation, valid_for: float = 1.0) -> str | None:
    reason = trigger.reason(o)
    if reason is not None:
        trigger.fired(o, o.t_s + valid_for)
    return reason


def test_first_call_always_decides() -> None:
    assert fire(Trigger(), obs(0.0)) == "first"


def test_quiet_flight_costs_one_decision_per_heartbeat() -> None:
    """With an intent that stays valid, nothing changing costs one decision per heartbeat --
    not one per MIN_PERIOD_S, which is the whole point of triggering on events."""
    tr = Trigger()
    fire(tr, obs(0.0), valid_for=60.0)
    t, fired = MIN_PERIOD_S, 0
    while t <= 20.0:
        fired += fire(tr, obs(t), valid_for=60.0) is not None
        t += MIN_PERIOD_S
    assert fired == round(20.0 / HEARTBEAT_S) == 4  # a fixed 0.5 s cadence would cost 40


def test_events_fire_and_the_floor_holds() -> None:
    tr = Trigger()
    fire(tr, obs(0.0))
    assert fire(tr, obs(0.1, program=64)) is None  # inside the floor: nothing yet
    assert fire(tr, obs(0.6, program=64)) == "program 63->64"
    assert fire(tr, obs(1.2, program=64, alarms=(0o1202,))) == "alarm 1202"
    assert fire(tr, obs(1.8, program=64, alarms=(0o1202,), radar_altitude_m=None)) == (
        "radar lock lost"
    )
    assert fire(tr, obs(2.4, program=64, alarms=(0o1202,), mode="manual")) == "mode auto->manual"


def test_an_expired_intent_asks_again_before_the_heartbeat() -> None:
    tr = Trigger()
    fire(tr, obs(0.0), valid_for=1.0)
    assert fire(tr, obs(0.6)) is None
    assert fire(tr, obs(1.1)) == "intent expired"
