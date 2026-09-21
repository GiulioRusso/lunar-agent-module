"""A cached AGC snapshot of everything before ignition (APOLLO_AGENT_PLAN.md Phase S, lever 1).

Every episode starts the same way, because **the dispersions change the world, never what the AGC
was told**: fresh start, hardware discretes, ~70 pad-load words through P27 (~57 s of AGC time),
REFSMMAT and its flag, RLS, TLAND, the LM and CSM state vectors, then `V37E63E` and ~60 s of
`IGNALG`, the R60 maneuver prompts and the countdown. That is minutes of wall clock, identical
every time, and yaAGC can resume from its own core dump.

So it is done once and reused: `build_snapshot` runs the slow path and saves the core plus the few
Python-side facts that cannot be read back out of it (the epoch the state vector was loaded at, the
landing time, the gimbal counts the CDUs were seeded to). `ready_agc` is what callers use -- it
resumes a yaAGC from the snapshot and hands back a process, a client and the `LandingSetup`, with
the AGC sitting exactly where the slow path left it.

The cache key covers everything that changes what the snapshot contains: the scenario, the rope
binary, and a version number to bump by hand when the setup sequence itself changes. A stale
snapshot is worse than a slow one, so when in doubt pass `refresh=True` (or delete the directory).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import DEFAULT_ROPE, AgcProcess
from luminary_agent.agc.symbols import SymbolTable
from luminary_agent.plant.discretes import Discretes
from luminary_agent.sim.frames import LunarFrame
from luminary_agent.sim.landing_scenario import DescentScenario, LandingSetup, prepare_landing
from luminary_agent.sim.p63_crew import start_p63

SNAPSHOT_VERSION = 1  # bump when the setup sequence changes what the AGC holds
DEFAULT_CACHE = Path("results/cache")
BOOT_INSTRUCTIONS = 30_000  # yaAGC opens its sockets only once its engine has run
DISPLAY_REFRESH_TRIES = 20  # one full DSKY multiplex cycle is ~1.4 s of AGC time


def snapshot_key(scenario: DescentScenario, rope: Path = DEFAULT_ROPE) -> str:
    rope_stat = rope.stat()
    material = json.dumps(
        {
            "version": SNAPSHOT_VERSION,
            "scenario": asdict(scenario),
            "rope": [rope.name, rope_stat.st_size, int(rope_stat.st_mtime)],
        },
        sort_keys=True,
    )
    return hashlib.sha1(material.encode()).hexdigest()[:16]


def snapshot_path(scenario: DescentScenario, cache_dir: Path = DEFAULT_CACHE) -> Path:
    return cache_dir / f"preignition-{snapshot_key(scenario)}.core"


def _setup_from_meta(scenario: DescentScenario, meta: dict[str, Any]) -> LandingSetup:
    """Rebuild the Python-side setup. Everything here is a pure function of the scenario and the
    two timestamps in the meta file -- no AGC needed, and it must match what `prepare_landing`
    computed when the snapshot was taken."""
    frame = LunarFrame.from_moon(meta["t_land_cs"])
    return LandingSetup(
        scenario,
        frame,
        frame.landing_refsmmat(scenario.theta_site),
        meta["now_cs"],
        meta["t_land_cs"],
    )


async def build_snapshot(
    workdir: Path,
    port: int,
    symbols: SymbolTable,
    scenario: DescentScenario,
    path: Path,
) -> None:
    """Run the slow pre-ignition path once and save it. Minutes; everything after is seconds."""
    async with AgcProcess(workdir, mode="stepped", port=port) as agc:
        await agc.step(BOOT_INSTRUCTIONS)
        async with AgcClient(port=port) as client:
            setup = await prepare_landing(agc, client, symbols, scenario)
            burn_attitude = await start_p63(agc, client, symbols)
            await agc.save_state(path)
    meta = {
        "version": SNAPSHOT_VERSION,
        "scenario": asdict(scenario),
        "now_cs": setup.now_cs,
        "t_land_cs": setup.t_land_cs,
        "burn_attitude": list(burn_attitude),
    }
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1))


async def ensure_snapshot(
    workdir: Path,
    port: int,
    symbols: SymbolTable,
    scenario: DescentScenario | None = None,
    cache_dir: Path = DEFAULT_CACHE,
    refresh: bool = False,
) -> Path:
    """Path to a usable snapshot, building it first if there is none. Call once before a batch:
    parallel workers would otherwise each build their own copy of the same thing."""
    scenario = scenario or DescentScenario()
    path = snapshot_path(scenario, cache_dir)
    if refresh or not path.exists() or not path.with_suffix(".json").exists():
        await build_snapshot(workdir, port, symbols, scenario, path)
    return path


@asynccontextmanager
async def ready_agc(
    workdir: Path,
    port: int,
    symbols: SymbolTable,
    scenario: DescentScenario | None = None,
    cache_dir: Path = DEFAULT_CACHE,
    refresh: bool = False,
) -> AsyncIterator[tuple[AgcProcess, AgcClient, LandingSetup, tuple[int, int, int]]]:
    """An AGC sitting at the pre-ignition countdown, resumed from the snapshot.

    Yields (process, client, setup, burn_attitude) -- the same four things the slow path produces,
    so `run_descent(..., burn_attitude=...)` picks up from here without knowing which path ran.
    """
    scenario = scenario or DescentScenario()
    path = await ensure_snapshot(workdir, port, symbols, scenario, cache_dir, refresh)
    meta = json.loads(path.with_suffix(".json").read_text())
    async with AgcProcess(workdir, mode="stepped", port=port, resume_from=path) as agc:
        await agc.step(BOOT_INSTRUCTIONS)
        async with AgcClient(port=port) as client:
            # Discretes live in input channels, which nothing re-asserts after a resume; the DAP
            # and the engine paths read them every T4RUPT, so write them back before anything else.
            await client.write_channels(Discretes(lr_position_1=True).channel_words())
            # The DSKY is multiplexed: T4RUPT sends one display row per 120 ms, so a client that
            # connects mid-flight sees nothing until a full refresh cycle has gone by. Step until
            # the display is populated, or the caller would read V=None for over a second.
            for _ in range(DISPLAY_REFRESH_TRIES):
                await agc.step(BOOT_INSTRUCTIONS)
                if client.dsky.verb_number is not None:
                    break
            burn = meta["burn_attitude"]
            yield agc, client, _setup_from_meta(scenario, meta), (burn[0], burn[1], burn[2])
