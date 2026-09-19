# luminary-agent

An LLM flight director closing the loop around the original 1969 Apollo Guidance Computer
software (Luminary 099, running unmodified in `yaAGC`) as it flies a simulated LM to the lunar
surface. Fully local: no APIs, no paid services.

See [`APOLLO_AGENT_PLAN.md`](../APOLLO_AGENT_PLAN.md) for the full build plan, phase gates, and
the flight-context taxonomy the scenario generator is built from.

## Status

Phase 0 (repo + emulator) in progress. No working demo yet.

## Setup

```sh
make setup   # uv sync + pre-commit install
make agc     # build yaYUL + yaAGC from the pinned virtualagc submodule
make test
```
