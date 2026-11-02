"""One scored episode: a policy (null = pure Luminary, scripted = fixed takeover rule, later an LLM)
flies a dispersed descent; prints one scored JSON line.

    python -m luminary_agent.eval.run_episode TIER SEED PORT WORKDIR --log episode.jsonl.gz

Arguments: TIER 1|2|3 (difficulty), SEED any int (which random episode), PORT first TCP port for
this episode's yaAGC (it uses PORT..PORT+9), WORKDIR scratch folder for yaAGC's files.
Options: --policy null|scripted, --no-safety, --no-surface.
`luminary fly` and `run_set` both end up calling `run()` below.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.eval.score import score
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.terrain import Surface
from luminary_agent.policies.agent_config import policy_configuration
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.safety.monitor import SafetyMonitor
from luminary_agent.scenarios.dispersions import sample
from luminary_agent.sim.descent import run_descent, summarize
from luminary_agent.sim.recorder import Recorder, evaluation_fingerprint, provenance
from luminary_agent.sim.snapshot import ready_agc
from luminary_agent.viz.live import LiveFeed


async def run(
    tier: int,
    seed: int,
    port: int,
    workdir: Path,
    log: Path,
    policy_name: str,
    safety: bool = True,
    surface_on: bool = True,
    live: LiveFeed | None = None,
) -> dict[str, Any]:
    """Fly one episode end to end, write its log, and return the result dict (also the .json)."""
    fingerprint = evaluation_fingerprint(
        {
            "tier": tier,
            "seed": seed,
            "policy": policy_name,
            "agent_config": policy_configuration(policy_name),
            "safety": safety,
            "surface": surface_on,
        }
    )
    # 1. Everything that makes this episode unique comes from (tier, seed).
    disp = sample(seed, tier)
    policy = POLICIES[policy_name]()
    monitor = SafetyMonitor() if safety else None
    surface = Surface.sample(seed) if surface_on else None
    sym = load_symbols(listing_path())  # variable-name -> address table from the build
    # Resumed from the cached pre-ignition snapshot: identical in every episode, so it is built
    # once and reused (sim/snapshot.py). Minutes saved per run.
    async with ready_agc(workdir, port, sym) as (agc, client, setup, burn_attitude):
        # 2. Log header: what produced this run (config + code/binary fingerprints).
        header = {
            "policy": policy_name,
            "evaluation_fingerprint": fingerprint,
            "instrument_model": "ideal_state_with_faulted_radar",
            "policy_config": getattr(policy, "config", {}),
            "tier": tier,
            "seed": seed,
            "clock_mode": "stepped",
            "safety_monitor": safety,
            "dispersion": asdict(disp),
            "surface": None if surface is None else surface.as_dict(),
            "site_x_m": setup.scenario.theta_site * R_MOON,
            **provenance(
                {
                    "tier": tier,
                    "seed": seed,
                    "scenario": asdict(setup.scenario),
                    "dispersion": asdict(disp),
                    "surface": None if surface is None else surface.as_dict(),
                }
            ),
        }
        with Recorder(log, header) as recorder:
            # 3. Fly. 4. Score. 5. Write the verdict as the log's last line.
            res = await run_descent(
                agc, client, sym, setup, recorder=recorder, max_sim_s=1200.0,
                dispersion=disp, policy=policy, monitor=monitor,
                burn_attitude=burn_attitude,
                live=live, surface=surface,
            )  # fmt: skip
            sc = score(res, disp.dry_mass_kg, surface)
            assessment = (
                surface.assess(res.downrange_error_m, res.lateral_m).as_dict()
                if surface is not None and res.outcome == "touchdown"
                else None
            )
            recorder.landing({"score": sc.as_dict(), "assessment": assessment})
    return {
        "evaluation_fingerprint": fingerprint,
        "instrument_model": "ideal_state_with_faulted_radar",
        "policy": policy_name,
        "tier": tier,
        "seed": seed,
        "dispersion": asdict(disp),
        "score": sc.as_dict(),
        "landing": assessment,
        "result": summarize(res, disp.dry_mass_kg),
        "agent_usage": {
            "calls": getattr(policy, "calls", 0),
            "tokens": getattr(policy, "tokens", 0),
        },
        "policy_config": getattr(policy, "config", {}),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", type=int)
    ap.add_argument("seed", type=int)
    ap.add_argument("port", type=int)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--policy", choices=sorted(POLICIES), default="null")
    ap.add_argument(
        "--no-surface", action="store_true", help="do not score mission_success (not_scored)"
    )
    ap.add_argument(
        "--no-safety", action="store_true", help="ablation: fly without the safety monitor"
    )
    a = ap.parse_args()
    result = asyncio.run(
        run(
            a.tier,
            a.seed,
            a.port,
            a.workdir,
            a.log,
            a.policy,
            safety=not a.no_safety,
            surface_on=not a.no_surface,
        )  # fmt: skip
    )
    print(json.dumps(result), flush=True)
