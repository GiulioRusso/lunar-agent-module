# luminary-agent

An LLM flight director closing the loop around the original 1969 Apollo Guidance Computer
software (Luminary 099, running unmodified in `yaAGC`) as it flies a simulated LM to the lunar
surface. Fully local: no APIs, no paid services.

See [`APOLLO_AGENT_PLAN.md`](APOLLO_AGENT_PLAN.md) for the full build plan, phase gates, and
the flight-context taxonomy the scenario generator is built from.

## Status

The simulator is complete and documented; the LLM agent is not started (Track B).

The original Luminary 099 rope flies a simulated LM from powered-descent initiation to a soft
landing (P63 -> P64 -> P65), closed through the emulator's accelerometer, gimbal-angle and throttle
channels. Around it: seeded dispersions (thrust, mass, propellant, an in-flight engine degradation,
radar bias and dropout, a hidden navigation error), a seeded lunar surface (target, craters,
boulders, slope), a scorer that keeps `soft_touchdown` and `mission_success` apart, an agent
interface (observe, decide, take manual control), a deterministic safety monitor with veto power,
event-driven decision triggering, provenance in every log, and a native pygame window (live during a
descent, or a replay of a recorded log). The same seed gives the same flight, bit for bit.

Code walkthrough, glossary and a file-by-file reference: [`README-simulator.md`](README-simulator.md).

## Run one

```sh
make agc                       # once: build the emulator (with patches/) and the Luminary rope
uv run luminary fly            # a full powered descent, live in a native window (pygame)
```

**~43 seconds** for a complete descent: 795 s of simulated flight at 22.8x real time, flown by the
original rope. `--tier 1|2|3 --seed N --policy null|scripted --no-ui` to vary it; `luminary view
<log.jsonl.gz>` replays a recorded one offline (no emulator, no browser, no server); `luminary eval --set dev` runs a batch.

The first run builds a cached pre-ignition AGC snapshot (~10 s, once): pad loads, REFSMMAT, state
vectors and the P63 crew prompts are identical in every episode, so they are done once and resumed
in 1.4 s (`luminary snapshot --refresh` rebuilds it).

Each episode writes `.json` (score: soft touchdown / mission success, touchdown speeds, target
error, propellant left, decisions, vetoes, and where the wall clock went) and `.jsonl.gz` (every
tick; replay it with `luminary view`). `make eval` runs the 15-episode dev set.

## Setup

```sh
make setup   # uv sync + pre-commit install
make agc     # build yaYUL + yaAGC from the pinned virtualagc submodule
make test    # unit tests (fast); integration tests need `make agc` first
make lint
```

## Pure Luminary vs a manual takeover

```sh
uv run luminary eval --set dev --policy null     --workers 5 --out results/logs/dev/null     --port 52000
uv run luminary eval --set dev --policy scripted --workers 5 --out results/logs/dev/scripted --port 53000
uv run python -m luminary_agent.eval.report --compare results/logs/dev
```

The baseline table (15 dev episodes per configuration, safety monitor on and off) and how to read
it are in [`docs/scenarios.md`](docs/scenarios.md). Give concurrent batches distinct `--port`s
(each emulator uses ten consecutive ports).

## Plugging in an agent

A policy implements `luminary_agent.policies.base.Policy` (`decide(obs, t_s) -> Intent`, `reset()`),
is registered in `policies/scripted.py:POLICIES`, and runs with
`python -m luminary_agent.eval.run_episode TIER SEED PORT WORKDIR --policy NAME --log ep.jsonl.gz`.
The simulation (plant and AGC) is paused while `decide` runs. See `sim/observation.py` for what it
sees and `sim/executor.py` for what it can do.

`decide` is called on events, not on a fixed cadence (`sim/events.py`): a program transition, a new
alarm, radar lock gained or lost, a mode change, the previous intent expiring, or a 5 s heartbeat,
with a 0.5 s floor. That is what keeps a slow policy affordable -- 20 s of quiet flight costs 4
decisions, not 40. Return a longer `valid_until_s` to be asked less often.

`safety/monitor.py` runs every tick on the same `Observation` the policy gets and can override it
(arrestable descent rate, horizontal speed near the ground). Vetoes are counted per episode,
marked in the replay's decision log, and `--no-safety` turns the monitor off for the ablation.
A policy cannot disable it.

Anything a policy reports as its configuration in `policy.config` (model, prompt hash, sampling
settings) is written into the episode header alongside the git SHA and clock mode.
