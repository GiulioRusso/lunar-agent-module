"""The entry point (CODE_REVIEW.md Phase V). One command, five verbs.

    luminary fly      [--tier 3 --seed 0 --policy scripted]   one descent, in a native window
    luminary view     <episode.jsonl.gz>                      replay a recorded one
    luminary eval     --set dev|frozen --policy null          the batch path
    luminary agc      build                                   emulator + rope, once
    luminary snapshot [--refresh]                             rebuild the pre-ignition cache

`fly` runs a full powered descent with the real Luminary 099 rope in the loop, records it, and
shows it live in a pygame window (no browser, no server); `--no-ui` runs it without one. `view`
plays a recorded log offline: no AGC, no emulator, no network. `python -m luminary_agent ...` and
`luminary ...` are the same thing.

How the command exists: pyproject.toml's [project.scripts] says `luminary =
"luminary_agent.__main__:main"`, so `uv sync` installs a `luminary` executable into .venv that
calls main() below. `uv run luminary ...` runs it inside the project's virtual environment.
Each verb is a subparser (argparse) whose `func` default points at the cmd_* function to run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
from pathlib import Path
from typing import Any

from luminary_agent.agc import build as agc_build
from luminary_agent.agc.build import listing_path
from luminary_agent.agc.symbols import load_symbols
from luminary_agent.eval import run_set
from luminary_agent.eval.run_episode import run as run_episode
from luminary_agent.eval.sets import SETS
from luminary_agent.plant.gravity import R_MOON
from luminary_agent.plant.terrain import Surface
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.scenarios.dispersions import sample
from luminary_agent.sim.landing_scenario import DescentScenario
from luminary_agent.sim.snapshot import ensure_snapshot
from luminary_agent.viz.live import BACKLOG, LiveFeed, LiveReader
from luminary_agent.viz.replay import load_episode, title

RUNS = Path("results/runs")  # default output folder for `fly` (relative to the current dir)


def _fly_child(kwargs: dict[str, Any], frames: Any, results: Any) -> None:
    """The descent, in its own process: it publishes frames to the window and reports the result.
    (A window in the same process starved the simulation's many small emulator round trips.)"""
    feed = LiveFeed(kwargs.pop("site_x_m"), kwargs.pop("dry_mass_kg"), frames)
    try:
        result = asyncio.run(run_episode(**kwargs, live=feed))
        results.put(("result", result))
        feed.publish_end(result["score"])
    except BaseException as exc:  # the window must not wait forever on a failed run
        results.put(("error", f"{type(exc).__name__}: {exc}"))
        feed.publish_end({"landed": False})
        raise


def cmd_fly(a: argparse.Namespace) -> None:
    """`luminary fly`: one episode, optionally with a live window; prints the verdict."""
    out = a.out or RUNS
    stem = out / f"t{a.tier}_s{a.seed}_{a.policy}"
    log = stem.with_suffix(".jsonl.gz")
    kwargs: dict[str, Any] = {
        "tier": a.tier, "seed": a.seed, "port": a.port,
        "workdir": out / f"work_t{a.tier}_s{a.seed}", "log": log, "policy_name": a.policy,
        "safety": not a.no_safety, "surface_on": not a.no_surface,
    }  # fmt: skip
    if a.no_ui:
        # No window: run the episode right here (asyncio.run starts the event loop).
        result = asyncio.run(run_episode(**kwargs))
    else:
        from luminary_agent.viz.native_app import run_live  # pygame only when a window is wanted

        # Two processes: a child flies the descent, this one runs the window. They talk through
        # two queues: `frames` (child -> window, view frames) and `results` (the final result).
        # "spawn" = start the child as a fresh Python interpreter (portable, macOS-safe).
        ctx = multiprocessing.get_context("spawn")
        frames, results = ctx.Queue(BACKLOG), ctx.Queue()
        child = ctx.Process(
            target=_fly_child,
            args=(
                kwargs | {
                    "site_x_m": DescentScenario().theta_site * R_MOON,
                    "dry_mass_kg": sample(a.seed, a.tier).dry_mass_kg,
                },
                frames, results,
            ),
            name="descent",
        )  # fmt: skip
        child.start()
        header = {"policy": a.policy, "tier": a.tier, "seed": a.seed}
        surface = None if a.no_surface else Surface.sample(a.seed)
        run_live(LiveReader(frames, title(header)), log, surface)  # blocks until window closes
        if child.is_alive():
            print("window closed; the episode keeps running")
        child.join()
        kind, payload = results.get()
        if kind == "error":
            raise SystemExit(f"the descent failed: {payload}")
        result = payload
    assert isinstance(result, dict)
    sc, res = result["score"], result["result"]
    verdict = (
        "SOFT TOUCHDOWN"
        if sc["soft_touchdown"]
        else ("LANDED, OUTSIDE LIMITS" if sc["landed"] else "NO LANDING")
    )
    print(
        f"\n{verdict}  vertical {sc['vertical_ms']:.2f} m/s  horizontal {sc['horizontal_ms']:.2f}"
        f" m/s  target {sc['target_error_m']:.0f} m  propellant {sc['fuel_kg']:.0f} kg left"
    )
    print(
        f"outcome {res['outcome']} at t={res['t_s']} s · decisions {res['decisions']} · "
        f"safety vetoes {res['safety_veto_count']} · fallbacks {res['fallback_count']} · "
        f"mission_success {sc['mission_success']} · alarms {res['alarms'] or 'none'}"
    )
    p = res.get("profile", {})
    if p:
        print(
            f"speed {p['speed_x_real_time']}x real time ({p['sim_s']} s flown in {p['wall_s']} s)"
            f" · {p['sections_s']} · unattributed {p['unattributed_s']} s"
        )
    stem.with_suffix(".json").write_text(json.dumps(result))  # the result next to the log
    print(log)


def cmd_view(a: argparse.Namespace) -> None:
    """`luminary view LOG`: replay a recorded episode, or save one frame as PNG."""
    from luminary_agent.viz import native_app

    episode = load_episode(a.episode, a.hz)
    if a.screenshot:
        native_app.screenshot(episode, a.at, a.screenshot, a.camera, inspect=a.inspect)
        print(a.screenshot)
    else:
        native_app.run_replay(episode)


def cmd_eval(a: argparse.Namespace) -> None:
    """`luminary eval`: a named set, or the cross product of --tiers x --seeds, in parallel."""
    jobs = list(SETS[a.set]) if a.set else [(t, s) for t in a.tiers for s in a.seeds]
    out = a.out or Path("results/logs") / (a.set or "batch")
    asyncio.run(run_set.main(jobs, a.workers, out, a.policy, a.port, safety=not a.no_safety))


def cmd_agc(a: argparse.Namespace) -> None:
    """`luminary agc build`: same as `make agc`."""
    agc_build.main()


def cmd_snapshot(a: argparse.Namespace) -> None:
    """`luminary snapshot [--refresh]`: build (or rebuild) the pre-ignition AGC cache."""
    sym = load_symbols(listing_path())
    path = asyncio.run(ensure_snapshot(RUNS / "snapshot_build", a.port, sym, refresh=a.refresh))
    print(path)


def agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=("openai", "anthropic", "ollama"))
    parser.add_argument("--model", help="model identifier for --policy llm")
    parser.add_argument("--base-url", help="optional model endpoint")
    parser.add_argument("--max-model-calls", type=int, help="per-episode model-call limit")


def parser() -> argparse.ArgumentParser:
    """All verbs and their options (this is what `luminary <verb> --help` prints)."""
    ap = argparse.ArgumentParser(prog="luminary", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fly", help="run one descent in a native window")
    f.add_argument("--tier", type=int, default=3, choices=(1, 2, 3))
    f.add_argument("--seed", type=int, default=0)
    f.add_argument("--policy", choices=sorted(POLICIES), default="scripted")
    f.add_argument("--no-ui", action="store_true", help="no window (batch, CI, ssh)")
    f.add_argument("--no-surface", action="store_true", help="do not score mission_success")
    f.add_argument("--no-safety", action="store_true", help="ablation: no safety monitor")
    f.add_argument("--out", type=Path, help=f"default: {RUNS}")
    f.add_argument("--port", type=int, default=19797)
    agent_options(f)
    f.set_defaults(func=cmd_fly)

    v = sub.add_parser("view", help="replay a recorded episode in a native window")
    v.add_argument("episode", type=Path)
    v.add_argument("--hz", type=float, default=10.0, help="frames per simulated second")
    v.add_argument("--screenshot", type=Path, help="write one PNG instead of opening a window")
    v.add_argument("--at", type=float, default=1e9, help="simulated time of the screenshot, s")
    v.add_argument("--camera", type=int, default=1, choices=(1, 2, 3))
    v.add_argument("--inspect", action="store_true", help="include agent inspector in screenshot")
    v.set_defaults(func=cmd_view)

    e = sub.add_parser("eval", help="run a set of episodes in parallel")
    e.add_argument("--set", choices=sorted(SETS), help="dev or frozen")
    e.add_argument("--tiers", type=int, nargs="+", default=[1, 2, 3])
    e.add_argument("--seeds", type=int, nargs="+", default=[0])
    e.add_argument("--policy", choices=sorted(POLICIES), default="null")
    e.add_argument("--workers", type=int, default=3)
    e.add_argument("--no-safety", action="store_true")
    e.add_argument("--out", type=Path)
    e.add_argument("--port", type=int, default=20100, help="base; each episode takes 10 ports")
    agent_options(e)
    e.set_defaults(func=cmd_eval)

    g = sub.add_parser("agc", help="build the emulator and assemble the rope")
    g.add_argument("what", nargs="?", default="build", choices=("build",))
    g.set_defaults(func=cmd_agc)

    s = sub.add_parser("snapshot", help="build the cached pre-ignition AGC state")
    s.add_argument("--refresh", action="store_true", help="rebuild even if one exists")
    s.add_argument("--port", type=int, default=19797)
    s.set_defaults(func=cmd_snapshot)
    return ap


def main() -> None:
    cli = parser()
    a = cli.parse_args()  # reads sys.argv
    import os

    for option, env in (
        ("provider", "LUMINARY_PROVIDER"),
        ("model", "LUMINARY_MODEL"),
        ("base_url", "LUMINARY_BASE_URL"),
        ("max_model_calls", "LUMINARY_MAX_CALLS"),
    ):
        if getattr(a, option, None) is not None:
            os.environ[env] = str(getattr(a, option))
    if getattr(a, "policy", None) == "llm":
        from luminary_agent.policies.agent_config import AgentConfig

        try:
            AgentConfig.from_env().check_credentials()
        except ValueError as exc:
            cli.error(str(exc))
    a.func(a)  # dispatch to cmd_fly / cmd_view / ...


if __name__ == "__main__":
    main()
