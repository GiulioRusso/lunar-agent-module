"""NullAgent baseline: pure Luminary flies a dispersed descent; prints one scored JSON line.

python -m luminary_agent.eval.run_null TIER SEED PORT WORKDIR [--log episode.jsonl.gz]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from luminary_agent.agc.build import listing_path
from luminary_agent.agc.client import AgcClient
from luminary_agent.agc.process import AgcProcess
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.eval.score import score
from luminary_agent.policies.manual_lander import ManualLander
from luminary_agent.scenarios.dispersions import sample
from luminary_agent.sim.descent import run_descent, summarize
from luminary_agent.sim.landing_scenario import prepare_landing
from luminary_agent.sim.recorder import Recorder


async def run(
    tier: int, seed: int, port: int, workdir: Path, log: Path | None, pilot_name: str = "none"
) -> dict[str, object]:
    disp = sample(seed, tier)
    pilot = ManualLander() if pilot_name == "manual" else None
    sym = load_symbols(listing_path())
    async with AgcProcess(workdir, mode="stepped", port=port) as agc:
        await agc.step(30_000)
        async with AgcClient(port=port) as c:
            setup = await prepare_landing(agc, c, sym)
            header = {"policy": pilot_name, "tier": tier, "seed": seed, "dispersion": disp.__dict__}
            if log is None:
                res = await run_descent(
                    agc, c, sym, setup, max_sim_s=1200.0, dispersion=disp, pilot=pilot
                )
            else:
                with Recorder(log, header) as rec:
                    res = await run_descent(
                        agc,
                        c,
                        sym,
                        setup,
                        recorder=rec,
                        max_sim_s=1200.0,
                        dispersion=disp,
                        pilot=pilot,
                    )
    return {"tier": tier, "seed": seed, "dispersion": disp.__dict__,
            "score": score(res, disp.dry_mass_kg).as_dict(), "result": summarize(res)}  # fmt: skip


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", type=int)
    ap.add_argument("seed", type=int)
    ap.add_argument("port", type=int)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--pilot", choices=["none", "manual"], default="none")
    a = ap.parse_args()
    print(
        json.dumps(asyncio.run(run(a.tier, a.seed, a.port, a.workdir, a.log, a.pilot))), flush=True
    )
