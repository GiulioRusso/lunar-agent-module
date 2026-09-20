.PHONY: setup agc test lint demo eval

setup:
	uv sync
	uv run pre-commit install

# build yaYUL + yaAGC from the pinned virtualagc submodule and assemble Luminary 099
agc:
	uv run python -m luminary_agent.agc.build

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy

demo:  # pure-Luminary descents (tiers 1-3, 2 seeds), ~40 min; replays land in results/logs/demo/*.html
	uv run python -m luminary_agent.eval.run_set --tiers 1 2 3 --seeds 0 1 --workers 3

eval:  # 15 dev episodes, pure Luminary
	uv run python -m luminary_agent.eval.run_set --set dev --out results/logs/dev
