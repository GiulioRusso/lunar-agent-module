.PHONY: setup agc run eval reproduce test lint

setup:
	uv sync
	uv run pre-commit install

# build yaYUL + yaAGC from the pinned virtualagc submodule and assemble Luminary 099
agc:
	uv run python -m luminary_agent.agc.build

run:
	uv run python -m luminary_agent

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run mypy

eval:
	uv run python -m luminary_agent.eval.runner

reproduce:
	uv run python -m luminary_agent.eval.runner --frozen
	uv run python -m luminary_agent.viz.figures
