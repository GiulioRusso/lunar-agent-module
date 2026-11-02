"""A full real-AGC descent with the actual LangGraph and an explicit fixture model."""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("langgraph")

from luminary_agent.agc.process import artifacts_present
from luminary_agent.eval.run_episode import run
from luminary_agent.policies.agent import FlightAgent
from luminary_agent.policies.agent_config import AgentConfig
from luminary_agent.policies.scripted import POLICIES
from luminary_agent.viz.replay import load_episode

pytestmark = pytest.mark.skipif(not artifacts_present(), reason="run make agc first")


class FixtureModel:
    """Only test plumbing; these canned rules do not demonstrate LLM piloting ability."""

    def invoke(self, messages: list[dict[str, str]]) -> Any:
        obs = json.loads(messages[-1]["content"])["observation"]
        altitude = obs["radar_altitude_m"]
        takeover = obs["mode"] == "auto" and (
            obs["program"] == 65 or altitude is not None and altitude < 150
        )
        return {
            "kind": "take_manual" if takeover else "hold",
            "rationale": "Fixture rule: take manual control low down."
            if takeover
            else "Fixture rule: retain current controller.",
            "evidence": [f"Mode {obs['mode']}", f"Radar altitude {altitude}"],
            "risks": ["Canned model response; not an LLM performance evaluation."],
            "plan": "Recheck altitude and authority at the next consultation.",
        }


def test_full_graph_descent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMINARY_MODEL", "fixture/no-llm")
    monkeypatch.setenv("LUMINARY_MAX_CALLS", "500")
    monkeypatch.setitem(
        POLICIES,
        "llm",
        lambda: FlightAgent(AgentConfig(model="fixture/no-llm", max_calls=500), FixtureModel()),
    )
    log = tmp_path / "agent.jsonl.gz"
    result = asyncio.run(run(1, 0, 31300, tmp_path / "work", log, "llm"))
    assert result["result"]["outcome"] == "touchdown"
    assert result["result"]["fallback_count"] == 0
    with gzip.open(log, "rt") as stream:
        records = [json.loads(line) for line in stream]
    assert any(r["type"] == "agent_status" and r["stage"] == "planning" for r in records)
    decisions = [r for r in records if r["type"] == "decision" and r.get("agent")]
    assert len(decisions) > 20
    assert all(r["agent"]["path"][-1] == "commit" for r in decisions)
    assert any(r["intent"]["kind"] == "take_manual" for r in decisions)
    assert load_episode(log).frames[-1].agent_model == "fixture/no-llm"
