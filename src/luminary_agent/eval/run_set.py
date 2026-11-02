"""Run a set of episodes (one policy) in parallel and print a results table.

    python -m luminary_agent.eval.run_set --tiers 1 2 3 --seeds 0 1 --workers 3
    python -m luminary_agent.eval.run_set --set dev --out results/logs/dev   # or --set frozen

Each episode takes ~20 min of CPU (a full powered descent through the real Luminary rope);
episodes are independent processes. **Each yaAGC occupies ten consecutive ports**: it binds
`--port` ... `--port+9` (`EstablishSocket(Portnum + NumServers)` for `MAX_CLIENTS` = 10,
yaAGC/SocketAPI.c:413). Ports are therefore handed out in steps of `PORTS_PER_AGC`; with a step of
1 the second episode's client connects to the *first* episode's AGC, two clients drive one rope,
and P63 stalls before ignition ("waited for V6 N61, last saw V37").

Per episode it writes <out>/t{tier}_s{seed}.{json,jsonl.gz}: the result and the recorded log
(replay it with `luminary view`). Re-running skips episodes whose .json already exists; one
failing episode is reported and does not stop the rest.

Parallelism: each episode is a separate Python process (`python -m ...run_episode`) with its own
yaAGC. asyncio.Semaphore(workers) lets at most `workers` of them run at once; the rest wait.
Episode i gets ports port_base + 10*i ... +9, so no two episodes ever share a port.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from luminary_agent.eval.report import summarize
from luminary_agent.eval.sets import SETS
from luminary_agent.policies.agent_config import policy_configuration
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.sim.recorder import evaluation_fingerprint

EPISODE_ATTEMPTS = 2  # a failed episode is retried once
PORTS_PER_AGC = 10  # yaAGC binds port .. port+9 (SocketAPI.c:413)


async def one(
    tier: int, seed: int, port: int, out: Path, policy: str, safety: bool = True
) -> dict[str, Any]:
    """Run one episode in a child Python process (unless its result already exists)."""
    stem = out / f"t{tier}_s{seed}"
    fingerprint = evaluation_fingerprint(
        {
            "tier": tier,
            "seed": seed,
            "policy": policy,
            "agent_config": policy_configuration(policy),
            "safety": safety,
            "surface": True,
        }
    )
    result_path = stem.with_suffix(".json")
    if result_path.exists():
        cached = json.loads(result_path.read_text())
        if cached.get("evaluation_fingerprint") != fingerprint:
            raise ValueError(
                f"incompatible cached result {result_path}; use a new output directory"
            )
    if not result_path.exists():
        # Belt and braces: the yaAGC input-thread stall that once hit ~2 % of parallel episodes is
        # fixed in patches/yaagc-free-run.patch (tests/integration/test_stepped_stress.py). Episodes
        # are deterministic, so a retry after any other transient failure is sound; it is announced.
        for attempt in range(1, EPISODE_ATTEMPTS + 1):
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "luminary_agent.eval.run_episode",
                str(tier), str(seed), str(port), str(out / f"work_t{tier}_s{seed}"),
                "--log", str(stem) + ".jsonl.gz", "--policy", policy,
                *([] if safety else ["--no-safety"]),
                stdout=asyncio.subprocess.PIPE,
            )  # fmt: skip
            stdout, _ = await proc.communicate()  # wait for it to finish, collect its output
            if proc.returncode == 0:
                break
            print(f"tier {tier} seed {seed}: attempt {attempt} failed", flush=True)
        else:  # for/else: runs only if the loop never hit `break` (every attempt failed)
            raise RuntimeError(f"episode tier {tier} seed {seed} failed (see its traceback above)")
        # run_episode prints its result as the last stdout line: save it as <stem>.json.
        stem.with_suffix(".json").write_text(stdout.decode().strip().splitlines()[-1])
    result: dict[str, Any] = json.loads(stem.with_suffix(".json").read_text())
    return result


async def main(
    jobs: list[tuple[int, int]],
    workers: int,
    out: Path,
    policy: str,
    port_base: int,
    safety: bool = True,
) -> None:
    """Run all (tier, seed) jobs, `workers` at a time, then print the summary table."""
    out.mkdir(parents=True, exist_ok=True)
    from luminary_agent.agc.build import listing_path
    from luminary_agent.agc.symbols import load_symbols
    from luminary_agent.sim.snapshot import ensure_snapshot

    if workers < 1:
        raise ValueError("workers must be positive")
    await ensure_snapshot(out / "snapshot_build", port_base, load_symbols(listing_path()))
    sem = asyncio.Semaphore(workers)  # at most `workers` episodes inside `async with sem`

    async def guarded(i: int, t: int, s: int) -> dict[str, Any]:
        async with sem:
            try:
                r = await one(t, s, port_base + PORTS_PER_AGC * i, out, policy, safety)
            except Exception as exc:  # one broken episode must not lose the other 59
                print(f"tier {t} seed {s}: ERROR {exc}", flush=True)
                return {"tier": t, "seed": s, "error": str(exc)}
        sc = r["score"]
        verdict = "SOFT" if sc["soft_touchdown"] else "FAIL"
        if sc["mission_success"] is True:
            verdict += "+MISSION"
        print(
            f"tier {t} seed {s}: {verdict}  vz {sc['vertical_ms']:.2f}  "
            f"vh {sc['horizontal_ms']:.2f}  target {sc['target_error_m']:.0f} m  "
            f"fuel {sc['fuel_kg']:.0f} kg",
            flush=True,
        )
        return r

    # Start every job concurrently; the semaphore throttles them. gather waits for all.
    results = await asyncio.gather(*(guarded(i, t, s) for i, (t, s) in enumerate(jobs)))
    failed = [r for r in results if "error" in r]
    soft = sum(1 for r in results if "error" not in r and r["score"]["soft_touchdown"])
    print(
        f"\n{soft}/{len(results) - len(failed)} soft touchdowns; replay: luminary view {out}/<log>"
    )
    if failed:
        names = ", ".join(f"t{r['tier']}_s{r['seed']}" for r in failed)
        print(f"{len(failed)} episode(s) failed: {names}")
    print()
    print(summarize(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("results/logs/demo"))
    ap.add_argument("--policy", choices=sorted(POLICIES), default="null")
    ap.add_argument(
        "--no-safety", action="store_true", help="ablation: fly without the safety monitor"
    )
    ap.add_argument(
        "--port-base", type=int, default=20100,
        help=f"distinct range per batch; each episode takes {PORTS_PER_AGC} consecutive ports",
    )  # fmt: skip
    ap.add_argument(
        "--set", choices=sorted(SETS), help="a frozen or dev set instead of tiers/seeds"
    )
    a = ap.parse_args()
    todo = list(SETS[a.set]) if a.set else [(t, s) for t in a.tiers for s in a.seeds]
    asyncio.run(main(todo, a.workers, a.out, a.policy, a.port_base, not a.no_safety))
