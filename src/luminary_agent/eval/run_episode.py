"""One scored episode: a policy (null = pure Luminary, scripted = fixed takeover rule, later an LLM)
flies a dispersed descent; prints one scored JSON line.

    python -m luminary_agent.eval.run_episode TIER SEED PORT WORKDIR --log episode.jsonl.gz
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.eval.score import score
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.scenarios.dispersions import sample
from luminary_agent.sim.descent import run_descent, summarize
from luminary_agent.sim.landing_scenario import prepare_landing
from luminary_agent.sim.recorder import Recorder


async def run(
    tier: int, seed: int, port: int, workdir: Path, log: Path, policy_name: str
) -> dict[str, Any]:
    disp = sample(seed, tier)
    policy = POLICIES[policy_name]()
    sym = load_symbols(listing_path())
    header = {"policy": policy_name, "tier": tier, "seed": seed, "dispersion": asdict(disp)}
    async with AgcProcess(workdir, mode="stepped", port=port) as agc:
        await agc.step(30_000)  # yaAGC opens its sockets only after its engine has run
        async with AgcClient(port=port) as client:
            setup = await prepare_landing(agc, client, sym)
            with Recorder(log, header) as recorder:
                res = await run_descent(
                    agc, client, sym, setup, recorder=recorder, max_sim_s=1200.0,
                    dispersion=disp, policy=policy,
                )  # fmt: skip
    return {
        "tier": tier,
        "seed": seed,
        "dispersion": asdict(disp),
        "score": score(res, disp.dry_mass_kg).as_dict(),
        "result": summarize(res),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", type=int)
    ap.add_argument("seed", type=int)
    ap.add_argument("port", type=int)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--policy", choices=sorted(POLICIES), default="null")
    a = ap.parse_args()
    print(
        json.dumps(asyncio.run(run(a.tier, a.seed, a.port, a.workdir, a.log, a.policy))), flush=True
    )
