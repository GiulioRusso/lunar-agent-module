"""Run a powered descent end to end: real Luminary 099, the plant, and the crew's DSKY answers.

Sequence (all through the flight software's own paths):
  1. crew prompts to P63's countdown (sim/p63_crew.py). Nothing thrusts yet, so the AGC is stepped
     on its own and the plant simply coasts -- fast-forwarded afterwards to the AGC's clock.
  2. from there the Simulation ticks every 20 ms: PIPA pulses in, engine/throttle/direction out
     (agc/actuators.py, agc/guidance.py, plant/throttle.py), recorded to an episode log.
  3. when Luminary asks for the engine (V99 N62, at TIG-4 s) the crew enables it (V33E), with
     keystrokes advancing the plant alongside.
Stops on touchdown, on Luminary leaving the landing programs (abort), or the time limit. Alarms
are recorded, not fatal. The outcome and its metrics are returned, never inferred by the caller.

A run can be checkpointed at a plant time and resumed later (`resume_descent`): the AGC's own
state via yaAGC's core dump, plus the plant, the throttle actuator and the loop's bookkeeping.
That turns a 17-minute run into a seconds-long experiment on any phase of the descent.

Known simplifications (a result must carry them): perfect pointing along the commanded thrust
vector, CDUs seeded at the burn attitude rather than slewed, the Moon's rotation not applied to
the plant (its effect on the *judgement* of a landing is handled in plant/surface.py).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.coredump import CoreDump
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.registers import REG_PIPAX, REG_PIPAY, REG_PIPAZ
from luminary_agent.agc.stepped_dsky import SteppedDsky
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.plant.dynamics import DT_S, Control, PlanarState, step
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.propulsion import DescentEngine
from luminary_agent.plant.radar import Radar
from luminary_agent.plant.surface import downrange_error_m, horizontal_speed_relative_to_surface
from luminary_agent.plant.terrain import Surface
from luminary_agent.plant.throttle import ThrottleActuator
from luminary_agent.policies.base import Intent, Policy
from luminary_agent.safety.monitor import SafetyMonitor
from luminary_agent.scenarios.dispersions import NOMINAL_DRY_MASS_KG, Dispersion
from luminary_agent.sim.clock import SteppedClock
from luminary_agent.sim.events import Trigger
from luminary_agent.sim.executor import Executor
from luminary_agent.sim.frames import LunarFrame
from luminary_agent.sim.landing_scenario import DescentScenario, LandingSetup
from luminary_agent.sim.loop import PipaAxes, Simulation, stepped_guidance_reader
from luminary_agent.sim.observation import Observation, surface_view
from luminary_agent.sim.p63_crew import start_p63
from luminary_agent.sim.recorder import Recorder

if TYPE_CHECKING:
    from luminary_agent.viz.live import LiveFeed

ALARM_CHECK_EVERY_TICKS = 50  # once per simulated second
FT_TO_M = 0.3048
LANDING_PROGRAMS = frozenset({63, 64, 65, 66, 67})


@dataclass
class DescentResult:
    outcome: str  # "touchdown" | "aborted" | "time_limit"
    t_s: float  # plant time since the state-vector epoch
    state: PlanarState
    alarms: list[int] = field(default_factory=list)
    ticks: int = 0
    site_angle_rad: float = 0.0
    lateral_m: float = 0.0  # cross-range position at the end (the target is at 0)
    engine_enabled_at_s: float | None = None
    decisions: int = 0  # times the policy was consulted (an LLM call each, in Track B)
    profile: dict[str, Any] = field(default_factory=dict)  # wall time per section (sim/meter.py)
    vetoes: list[str] = field(default_factory=list)  # safety-monitor overrides, in order
    notes: list[str] = field(default_factory=list)

    @property
    def vertical_ms(self) -> float:
        return self.state.hdot_ms

    @property
    def horizontal_relative_ms(self) -> float:
        return horizontal_speed_relative_to_surface(self.state)

    @property
    def downrange_error_m(self) -> float:
        return downrange_error_m(self.state, self.site_angle_rad)


def coast(state: PlanarState, seconds: float, engine: DescentEngine | None = None) -> PlanarState:
    """Propagate the plant with the engine off (used to catch it up to the AGC's clock)."""
    engine = engine or DescentEngine()
    control = Control(throttle=0.0, pitch_rad=0.0)
    steps = round(seconds / DT_S)
    for _ in range(steps):
        state = step(state, control, engine, DT_S)
    return state


def _make_sim(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    setup: LandingSetup,
    clock: SteppedClock,
    state: PlanarState,
    t_offset_s: float,
    recorder: Recorder | None,
    engine: DescentEngine | None = None,
    dry_mass_kg: float | None = None,
    live: LiveFeed | None = None,
) -> Simulation:
    return Simulation(
        client,
        clock,
        state,
        PipaAxes(x=REG_PIPAX, y=REG_PIPAY, z=REG_PIPAZ),
        setup.frame,
        setup.refsmmat,
        recorder=recorder,
        actuator=ThrottleActuator(),
        read_guidance_sample=stepped_guidance_reader(agc, symbols),
        t_offset_s=t_offset_s,
        engine=engine,
        dry_mass_kg=dry_mass_kg,
        live=live,
    )


def observe(
    sim: Simulation,
    client: AgcClient,
    mode: str,
    t: float,
    alarms: list[int],
    radar: Radar,
    surface: Surface | None = None,
    site_x_m: float = 0.0,
) -> Observation:
    d, s = client.dsky, sim.state
    dry = sim.dry_mass_kg if sim.dry_mass_kg is not None else NOMINAL_DRY_MASS_KG
    # Luminary's own altitude is the DSKY's R3 (feet) while N63/N64 is displayed.
    shows_altitude = d.program_number in (63, 64) and d.noun_number in (63, 64)
    agc_alt = d.r3 * FT_TO_M if shows_altitude and d.r3 is not None else None
    return Observation(
        t, mode, d.program_number, d.verb_number, d.noun_number, d.r1, d.r2, d.r3, tuple(alarms),
        radar.altitude(s.h_m, t), agc_alt, s.hdot_ms, horizontal_speed_relative_to_surface(s),
        sim.thrust_n, s.mass_kg, max(0.0, s.mass_kg - dry),
        **surface_view(surface, s.x_m - site_x_m, sim.z_m, s.h_m),
    )  # fmt: skip


async def _act(
    executor: Executor,
    sim: Simulation,
    obs: Observation,
    intent: Intent,
    notes: list[str],
    *,
    reason: str,
    latency_s: float,
    veto: bool = False,
) -> None:
    """Apply one intent (an agent's or the safety monitor's) and log what happened. `reason` is
    what asked for the decision (sim/events.py) or what the monitor objected to."""
    applied = await executor.apply(intent)
    record = {
        "t": round(obs.t_s, 3),
        "obs": obs.to_dict(),
        "intent": {"kind": intent.kind, "params": intent.params},
        "applied": applied,
        "latency_s": round(latency_s, 4),
        "reason": reason,
        **({"veto": True} if veto else {}),
    }
    if sim.recorder is not None:
        sim.recorder.event(record)
    if sim.live is not None:
        sim.live.publish_decision(record)
    if intent.kind == "take_manual" and applied.startswith("ok"):
        who = "safety monitor" if veto else "agent"
        notes.append(f"manual takeover ({who}) at plant t={obs.t_s:.1f} s, h={sim.state.h_m:.0f} m")


async def _consult(
    policy: Policy,
    executor: Executor,
    sim: Simulation,
    obs: Observation,
    reason: str,
    notes: list[str],
) -> Intent:
    """One agent decision: decide (the whole simulation is paused meanwhile), apply, log."""
    started = time.perf_counter()
    intent = policy.decide(obs, obs.t_s)
    latency_s = time.perf_counter() - started
    await _act(executor, sim, obs, intent, notes, reason=reason, latency_s=latency_s)
    return intent


async def _fly(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    setup: LandingSetup,
    sim: Simulation,
    clock: SteppedClock,
    t_start_s: float,
    max_sim_s: float,
    engine_enabled_at: float | None,
    notes: list[str],
    on_second: Callable[[Simulation, CoreDump], None] | None,
    checkpoint: tuple[float, Path] | None,
    policy: Policy | None,
    disp: Dispersion,
    monitor: SafetyMonitor | None,
    surface: Surface | None = None,
) -> DescentResult:
    dsky = SteppedDsky(agc, client, advance=sim.advance_instructions)
    failreg = symbols.ecadr("FAILREG")
    modreg = symbols.ecadr("MODREG")
    alarms_seen: list[int] = []
    landing_started = False
    checkpointed = False
    result: DescentResult | None = None
    executor = Executor(sim, client)
    trigger = Trigger()
    decisions = 0
    radar = disp.radar
    faulted = disp.thrust_fault_at_s <= 0.0  # nothing to apply
    if policy is not None:
        policy.reset()

    while result is None:
        await sim.tick()
        t = sim.t_offset_s + clock.sim_time_s

        if not faulted and t >= disp.thrust_fault_at_s:
            # In-flight engine degradation: the AGC is told nothing and compensates with throttle,
            # so the only visible symptom is the propellant margin (scenarios/dispersions.py).
            sim.engine = disp.engine(faulted=True)
            faulted = True
            notes.append(
                f"engine degraded to {disp.thrust_fault_scale:.0%} thrust at plant t={t:.1f} s"
            )

        if policy is not None:
            obs = observe(
                sim,
                client,
                executor.mode,
                t,
                alarms_seen,
                radar,
                surface,
                setup.scenario.theta_site * R_MOON,
            )
            # The monitor runs every tick and outranks the policy; the policy is consulted only
            # when something changed (sim/events.py).
            veto = monitor.check(obs) if monitor is not None else None
            if veto is not None:
                await _act(
                    executor, sim, obs, veto.intent, notes,
                    reason=veto.reason, latency_s=0.0, veto=not veto.release,
                )  # fmt: skip
                trigger.fired(obs, veto.intent.valid_until_s)
            elif (reason := trigger.reason(obs)) is not None:
                intent = await _consult(policy, executor, sim, obs, reason, notes)
                decisions += 1
                trigger.fired(obs, intent.valid_until_s)
        d = client.dsky
        if engine_enabled_at is None and d.verb_number == 99 and d.noun_number == 62:
            await dsky.verb(33)  # the crew enables the engine
            engine_enabled_at = sim.t_offset_s + clock.sim_time_s
            notes.append(f"engine enabled (V99 N62 answered) at plant t={engine_enabled_at:.1f} s")

        if checkpoint is not None and not checkpointed and t >= checkpoint[0]:
            await save_checkpoint(agc, sim, setup, checkpoint[1], engine_enabled_at)
            checkpointed = True

        if sim.state.h_m <= 0.0:
            result = DescentResult("touchdown", t, sim.state)
        elif t - t_start_s >= max_sim_s:
            result = DescentResult("time_limit", t, sim.state)
        elif sim.ticks % ALARM_CHECK_EVERY_TICKS == 0:
            with sim.meter.section("alarms"):
                dump = await agc.coredump()
            if on_second is not None:
                on_second(sim, dump)
            # Alarms are informational, as in real operations (1201/1202 did not end Apollo 11's
            # landing; 0401 "gimbal lock" is Luminary's own attitude arithmetic, which this plant
            # -- perfectly pointed, no gimbals -- does not feel). They are recorded, not fatal.
            for w in dump.ecadr_words(failreg, 3):
                if w and w not in alarms_seen:
                    alarms_seen.append(w)
            mode = dump.erasable_signed(*divmod(modreg, 0o400))
            if mode in LANDING_PROGRAMS:
                landing_started = True
            elif landing_started:
                # Left the landing programs for P00 etc.: Luminary aborted the descent.
                result = DescentResult("aborted", t, sim.state, notes=[f"MODREG={mode}"])

    result.ticks = sim.ticks
    result.profile = sim.meter.report(sim_s=max(0.0, t - t_start_s))
    result.decisions = decisions
    result.vetoes = [f"t={v.t_s:.1f}s {v.reason}" for v in (monitor.vetoes if monitor else [])]
    result.alarms = alarms_seen
    result.site_angle_rad = setup.scenario.theta_site
    result.lateral_m = sim.z_m
    result.engine_enabled_at_s = engine_enabled_at
    result.notes = notes + result.notes
    return result


async def run_descent(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    setup: LandingSetup,
    recorder: Recorder | None = None,
    max_sim_s: float = 900.0,
    on_second: Callable[[Simulation, CoreDump], None] | None = None,
    checkpoint: tuple[float, Path] | None = None,
    dispersion: Dispersion | None = None,
    policy: Policy | None = None,
    monitor: SafetyMonitor | None = None,
    burn_attitude: tuple[int, int, int] | None = None,
    live: LiveFeed | None = None,
    surface: Surface | None = None,
) -> DescentResult:
    """`policy` is called on a cadence with an Observation and returns an Intent (sim/executor.py);
    the simulation is paused while it decides. `dispersion` makes the plant differ from what the
    AGC was told (scenarios/dispersions.py). `on_second`, if given, is called once per simulated
    second with the plant and a fresh core dump (compare the AGC's belief with the truth).
    `checkpoint` = (plant time in s since the epoch, path) saves a resumable checkpoint then.
    `burn_attitude`, when given, means the AGC is already past the P63 crew prompts (it was
    resumed from a snapshot) and those gimbal counts are what the CDUs were seeded to.
    """
    epoch_s = setup.now_cs / 100.0
    if burn_attitude is None:  # the slow path: run the crew prompts now
        burn_attitude = await start_p63(agc, client, symbols)
        notes = [f"CDUs seeded at burn attitude {burn_attitude} (no attitude dynamics)"]
    else:  # resumed from the pre-ignition snapshot (sim/snapshot.py), which already did
        notes = [f"pre-ignition snapshot; CDUs seeded at burn attitude {burn_attitude}"]

    # The plant coasted while only the crew was talking to the AGC: catch it up.
    dump = await agc.coredump()
    elapsed_s = dump.clock_cs / 100.0 - epoch_s
    disp = dispersion or Dispersion()
    state = coast(disp.apply(setup.scenario.start_state), elapsed_s, disp.engine())

    clock = SteppedClock(agc)
    await clock.start()
    sim = _make_sim(
        agc,
        client,
        symbols,
        setup,
        clock,
        state,
        elapsed_s,
        recorder,
        disp.engine(),
        disp.dry_mass_kg,
        live,
    )
    return await _fly(
        agc, client, symbols, setup, sim, clock, elapsed_s, max_sim_s, None, notes,
        on_second, checkpoint, policy, disp, monitor, surface,
    )  # fmt: skip


# --- checkpoint / resume ----------------------------------------------------------------


async def save_checkpoint(
    agc: AgcProcess,
    sim: Simulation,
    setup: LandingSetup,
    path: Path,
    engine_enabled_at: float | None,
) -> None:
    """Write `path` (JSON: plant, actuator, loop state) and `path`.core (the AGC's state)."""
    assert sim.actuator is not None
    core = path.with_suffix(".core")
    await agc.save_state(core)
    s, a = sim.state, sim.actuator
    path.write_text(
        json.dumps(
            {
                "plant": [s.h_m, s.x_m, s.hdot_ms, s.xdot_ms, s.mass_kg],
                "t_plant_s": sim.t_offset_s + sim.clock.sim_time_s,
                "actuator": [a.counts, a.pending, a.engine_on],
                "pitch_rad": sim.pitch_rad,
                "thrust_scale": sim.engine.f_max_n / DescentEngine().f_max_n,
                "dry_mass_kg": sim.dry_mass_kg,
                "lateral": [sim.z_m, sim.zdot_ms, sim.normal_fraction],
                "stamp_seen": sim._stamp_seen,
                "ticks": sim.ticks,
                "engine_enabled_at": engine_enabled_at,
                "setup": {"now_cs": setup.now_cs, "t_land_cs": setup.t_land_cs},
                "core": core.name,
            }
        )
    )


async def resume_descent(
    agc: AgcProcess,
    client: AgcClient,
    symbols: SymbolTable,
    checkpoint_path: Path,
    recorder: Recorder | None = None,
    max_sim_s: float = 900.0,
    on_second: Callable[[Simulation, CoreDump], None] | None = None,
) -> DescentResult:
    """Continue a checkpointed descent. `agc` must be a stepped AgcProcess started with
    `resume_from=<checkpoint>.core` and already stepped once (yaAGC opens its sockets only once
    its engine has run) so that `client` could connect.
    """
    saved: dict[str, Any] = json.loads(checkpoint_path.read_text())
    scenario = DescentScenario()
    now_cs, t_land_cs = saved["setup"]["now_cs"], saved["setup"]["t_land_cs"]
    frame = LunarFrame.from_moon(t_land_cs)
    setup = LandingSetup(
        scenario, frame, frame.landing_refsmmat(scenario.theta_site), now_cs, t_land_cs
    )

    clock = SteppedClock(agc)
    await clock.start()
    h, x, hdot, xdot, mass = saved["plant"]
    disp = Dispersion(thrust_scale=saved.get("thrust_scale", 1.0))
    dry = saved.get("dry_mass_kg")
    sim = _make_sim(agc, client, symbols, setup, clock, PlanarState(h, x, hdot, xdot, mass),
                    saved["t_plant_s"], recorder, disp.engine(), dry)  # fmt: skip
    assert sim.actuator is not None
    sim.actuator.counts, sim.actuator.pending, sim.actuator.engine_on = saved["actuator"]
    sim.pitch_rad = saved["pitch_rad"]
    sim.z_m, sim.zdot_ms, sim.normal_fraction = saved.get("lateral", (0.0, 0.0, 0.0))
    sim._stamp_seen = saved["stamp_seen"]
    sim.ticks = saved["ticks"]
    client.actuators.engine_on = sim.actuator.engine_on  # the AGC re-announces it on connect too
    notes = [f"resumed from {checkpoint_path.name} at plant t={saved['t_plant_s']:.1f} s"]
    return await _fly(
        agc, client, symbols, setup, sim, clock, saved["t_plant_s"], max_sim_s,
        saved["engine_enabled_at"], notes, on_second, None, None, disp, None,
    )  # fmt: skip


def summarize(result: DescentResult, dry_mass_kg: float = NOMINAL_DRY_MASS_KG) -> dict[str, Any]:
    s = result.state
    fuel_kg = max(0.0, s.mass_kg - dry_mass_kg)
    return {
        "outcome": result.outcome,
        "t_s": round(result.t_s, 1),
        "h_m": round(s.h_m, 1),
        "hdot_ms": round(s.hdot_ms, 2),
        "vt_inertial_ms": round(s.xdot_ms, 2),
        "horizontal_relative_to_surface_ms": round(result.horizontal_relative_ms, 2),
        "downrange_error_m": round(result.downrange_error_m, 0),
        "lateral_m": round(result.lateral_m, 0),
        "target_error_m": round(math.hypot(result.downrange_error_m, result.lateral_m), 0),
        "fuel_kg": round(fuel_kg, 1),
        "mass_kg": round(s.mass_kg, 1),
        "alarms": [oct(a) for a in result.alarms],
        "decisions": result.decisions,
        "vetoes": result.vetoes,
        "safety_veto_count": len(result.vetoes),
        "fallback_count": 0,
        "profile": result.profile,
        "engine_enabled_at_s": result.engine_enabled_at_s,
        "notes": result.notes,
    }
