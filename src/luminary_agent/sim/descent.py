"""Run a powered descent end to end: real Luminary 099, the plant, and the crew's DSKY answers.

Sequence (all through the flight software's own paths):
  1. crew prompts to P63's countdown (sim/p63_crew.py). Nothing thrusts yet, so the AGC is stepped
     on its own and the plant simply coasts -- fast-forwarded afterwards to the AGC's clock.
  2. from there the Simulation ticks every 20 ms: PIPA pulses in, engine/throttle/direction out
     (agc/actuators.py, agc/guidance.py, plant/throttle.py), recorded to an episode log.
  3. when Luminary asks for the engine (V99 N62, at TIG-4 s) the crew enables it (V33E), with
     keystrokes advancing the plant alongside.
Stops on touchdown, a program alarm, or the time limit. The outcome and its metrics are returned,
never inferred by the caller.

Known simplifications (a result must carry them): perfect pointing along the commanded thrust
vector, CDUs seeded at the burn attitude rather than slewed, the Moon's rotation ignored.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import CoreDump
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.registers import REG_PIPAX, REG_PIPAY, REG_PIPAZ
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.throttle import ThrottleActuator
from luminary_agent.sim.clock import SteppedClock
from luminary_agent.sim.landing_scenario import LandingSetup
from luminary_agent.sim.loop import PipaAxes, Simulation, stepped_guidance_reader
from luminary_agent.sim.p63_crew import start_p63
from luminary_agent.sim.recorder import Recorder

ALARM_CHECK_EVERY_TICKS = 50  # once per simulated second


@dataclass
class DescentResult:
    outcome: str  # "touchdown" | "alarm" | "time_limit"
    t_s: float  # plant time since the state-vector epoch
    state: PlanarState
    alarms: list[int] = field(default_factory=list)
    ticks: int = 0
    engine_enabled_at_s: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def touchdown_vertical_ms(self) -> float:
        return self.state.hdot_ms


def coast(state: PlanarState, seconds: float, engine: DescentEngine | None = None) -> PlanarState:
    """Propagate the plant with the engine off (used to catch it up to the AGC's clock)."""
    engine = engine or DescentEngine()
    control = Control(throttle=0.0, pitch_rad=0.0)
    steps = round(seconds / DT_S)
    for _ in range(steps):
        state = step(state, control, engine, DT_S)
    return state


async def run_descent(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    setup: LandingSetup,
    recorder: Recorder | None = None,
    max_sim_s: float = 900.0,
    on_second: Callable[[Simulation, CoreDump], None] | None = None,
) -> DescentResult:
    """`on_second`, if given, is called once per simulated second with the plant and a fresh
    core dump -- the hook for comparing the AGC's belief with the plant's truth.
    """
    epoch_s = setup.now_cs / 100.0
    burn_attitude = await start_p63(agc, client, symbols)
    notes = [f"CDUs seeded at burn attitude {burn_attitude} (no attitude dynamics)"]

    # The plant coasted while only the crew was talking to the AGC: catch it up.
    dump = await agc.coredump()
    elapsed_s = dump.clock_cs / 100.0 - epoch_s
    state = coast(setup.scenario.start_state, elapsed_s)

    clock = SteppedClock(agc)
    await clock.start()
    sim = Simulation(
        client,
        clock,
        state,
        PipaAxes(x=REG_PIPAX, y=REG_PIPAY, z=REG_PIPAZ),
        setup.frame,
        setup.refsmmat,
        recorder=recorder,
        actuator=ThrottleActuator(),
        read_guidance_sample=stepped_guidance_reader(agc, symbols),
        t_offset_s=elapsed_s,
    )
    dsky = SteppedDsky(agc, client, advance=sim.advance_instructions)
    failreg = symbols.ecadr("FAILREG")
    engine_enabled_at: float | None = None
    result: DescentResult | None = None

    while result is None:
        await sim.tick()
        t = elapsed_s + clock.sim_time_s

        d = client.dsky
        if engine_enabled_at is None and d.verb_number == 99 and d.noun_number == 62:
            await dsky.verb(33)  # the crew enables the engine
            engine_enabled_at = elapsed_s + clock.sim_time_s
            notes.append(f"engine enabled (V99 N62 answered) at plant t={engine_enabled_at:.1f} s")

        if sim.state.h_m <= 0.0:
            result = DescentResult("touchdown", t, sim.state)
        elif t - elapsed_s >= max_sim_s:
            result = DescentResult("time_limit", t, sim.state)
        elif sim.ticks % ALARM_CHECK_EVERY_TICKS == 0:
            dump = await agc.coredump()
            if on_second is not None:
                on_second(sim, dump)
            alarms = [w for w in dump.ecadr_words(failreg, 3) if w]
            if alarms:
                result = DescentResult("alarm", t, sim.state, alarms=alarms)

    result.ticks = sim.ticks
    result.engine_enabled_at_s = engine_enabled_at
    result.notes = notes
    return result


def summarize(result: DescentResult) -> dict[str, Any]:
    s = result.state
    return {
        "outcome": result.outcome,
        "t_s": round(result.t_s, 1),
        "h_m": round(s.h_m, 1),
        "hdot_ms": round(s.hdot_ms, 2),
        "vt_ms": round(s.xdot_ms, 2),
        "mass_kg": round(s.mass_kg, 1),
        "alarms": [oct(a) for a in result.alarms],
        "engine_enabled_at_s": result.engine_enabled_at_s,
        "notes": result.notes,
    }
