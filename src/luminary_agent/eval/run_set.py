"""Run a set of NullAgent episodes in parallel and print a results table.

    python -m luminary_agent.eval.run_set --tiers 1 2 3 --seeds 0 1 --workers 3
    python -m luminary_agent.eval.run_set --set dev --out results/logs/dev   # or --set frozen

Each episode takes ~20 min of CPU (a full powered descent through the real Luminary rope);
episodes are independent processes. Per episode it writes <out>/t{tier}_s{seed}.{json,jsonl.gz,html}
(result, recorded log, replayable viewer). Re-running skips episodes whose .json already exists.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from luminary_agent.eval.report import summarize
from luminary_agent.eval.sets import SETS
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.viz.replay import build


async def one(tier: int, seed: int, port: int, out: Path, policy: str) -> dict[str, object]:
    stem = out / f"t{tier}_s{seed}"
    if not stem.with_suffix(".json").exists():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "luminary_agent.eval.run_episode",
            str(tier), str(seed), str(port), str(out / f"work_t{tier}_s{seed}"),
            "--log", str(stem) + ".jsonl.gz", "--policy", policy,
            stdout=asyncio.subprocess.PIPE,
        )  # fmt: skip
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"episode tier {tier} seed {seed} failed (see its traceback above)")
        stem.with_suffix(".json").write_text(stdout.decode().strip().splitlines()[-1])
        build(Path(str(stem) + ".jsonl.gz"), stem.with_suffix(".html"))
    return json.loads(stem.with_suffix(".json").read_text())  # type: ignore[no-any-return]


async def main(
    jobs: list[tuple[int, int]], workers: int, out: Path, policy: str, port_base: int
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(workers)

    async def guarded(i: int, t: int, s: int) -> dict[str, object]:
        async with sem:
            r = await one(t, s, port_base + i, out, policy)
        sc = r["score"]
        assert isinstance(sc, dict)
        verdict = "SAFE" if sc["safe"] else "FAIL"
        print(
            f"tier {t} seed {s}: {verdict}  vz {sc['vertical_ms']:.2f}  "
            f"vh {sc['horizontal_ms']:.2f}  site {sc['site_error_m']:.0f} m  "
            f"fuel {sc['fuel_kg']:.0f} kg",
            flush=True,
        )
        return r

    results = await asyncio.gather(*(guarded(i, t, s) for i, (t, s) in enumerate(jobs)))
    safe = sum(1 for r in results if r["score"]["safe"])  # type: ignore[index, misc]
    print(f"\n{safe}/{len(results)} safe landings; replays: {out}/*.html\n")
    print(summarize(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("results/logs/demo"))
    ap.add_argument("--policy", choices=sorted(POLICIES), default="null")
    ap.add_argument("--port-base", type=int, default=20100, help="distinct range per batch")
    ap.add_argument(
        "--set", choices=sorted(SETS), help="a frozen or dev set instead of tiers/seeds"
    )
    a = ap.parse_args()
    todo = list(SETS[a.set]) if a.set else [(t, s) for t in a.tiers for s in a.seeds]
    asyncio.run(main(todo, a.workers, a.out, a.policy, a.port_base))
