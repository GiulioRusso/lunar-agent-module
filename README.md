# luminary-agent

An LLM flight director closing the loop around the original 1969 Apollo Guidance Computer
software (Luminary 099, running unmodified in `yaAGC`) as it flies a simulated LM to the lunar
surface. Fully local: no APIs, no paid services.

See [`APOLLO_AGENT_PLAN.md`](APOLLO_AGENT_PLAN.md) for the full build plan, phase gates, and
the flight-context taxonomy the scenario generator is built from.

## Status

Track A works end to end for the unassisted baseline: the original Luminary 099 rope flies a
simulated LM from powered-descent initiation to a soft landing (P63 -> P64 -> P65), closed through
the emulator's PIPA/CDU/throttle channels, with seeded dispersions, a scorer, and an HTML replay.
No LLM agent yet (Track B).

## See results

```sh
make agc        # once: build the emulator and the Luminary rope
make demo       # 3 difficulty tiers x 2 seeds, pure Luminary, in parallel (~40 min)
open results/logs/demo/t1_s0.html     # replay of one descent (1x, pause, scrub, 0.5-20x)
```

Each episode also writes `t{tier}_s{seed}.json` (score: landed/safe, touchdown speeds, site error,
propellant left) and the full recorded log. One episode alone:
`uv run python -m luminary_agent.eval.run_set --tiers 2 --seeds 0 --workers 1`.

## Setup

```sh
make setup   # uv sync + pre-commit install
make agc     # build yaYUL + yaAGC from the pinned virtualagc submodule
make test
```

## Pure Luminary vs a manual takeover

```sh
uv run python -m luminary_agent.eval.run_set --tiers 3 --seeds 0 1 --workers 2 --port-base 20200 --out results/logs/nullhard
uv run python -m luminary_agent.eval.run_set --tiers 3 --seeds 0 1 --workers 2 --port-base 20300 --policy scripted --out results/logs/pilot
```

Tier 3 hides a navigation error from the AGC. Luminary alone crashes (0/2 safe); a crew taking
manual throttle and reading the radar lands 2/2. Give concurrent batches distinct `--port-base`s.

## Plugging in an agent

A policy implements `luminary_agent.policies.base.Policy` (`decide(obs, t_s) -> Intent`, `reset()`),
is registered in `policies/scripted.py:POLICIES`, and runs with
`python -m luminary_agent.eval.run_episode TIER SEED PORT WORKDIR --policy NAME --log ep.jsonl.gz`.
The simulation (plant and AGC) is paused while `decide` runs. See `sim/observation.py` for what it
sees and `sim/executor.py` for what it can do.
