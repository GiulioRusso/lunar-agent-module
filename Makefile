.PHONY: setup agc test lint fly view demo eval frozen
POLICY ?= scripted
TIER ?= 3
SEED ?= 0
PORT ?= 20600

setup:
	uv sync
	uv run pre-commit install

# build yaYUL + yaAGC from the pinned virtualagc submodule and assemble Luminary 099
agc:
	uv run python -m luminary_agent.agc.build

test:
	uv run --extra agent pytest

lint:
	uv run ruff check .
	uv run --extra agent mypy

fly:  # one descent in a native window: make fly TIER=3 SEED=0 POLICY=scripted  (add UI=--no-ui to skip it)
	uv run luminary fly --tier $(TIER) --seed $(SEED) --policy $(POLICY) $(UI)

demo:  # pure-Luminary descents (tiers 1-3, 2 seeds), ~40 min; logs land in results/logs/demo/; replay one with `make view`
	uv run python -m luminary_agent.eval.run_set --tiers 1 2 3 --seeds 0 1 --workers 3

eval:  # 15 dev episodes, pure Luminary (~1.7 h at 3 workers)
	uv run python -m luminary_agent.eval.run_set --set dev --out results/logs/dev

view:  # replay a recorded episode in a native window: make view LOG=results/runs/t3_s0_scripted.jsonl.gz
	uv run luminary view $(LOG)

frozen:  # the 60 frozen eval episodes -- results only, never tune on these (~7 h at 3 workers)
	uv run python -m luminary_agent.eval.run_set --set frozen --out results/logs/frozen/$(POLICY) \
		--policy $(POLICY) --port-base $(PORT)
