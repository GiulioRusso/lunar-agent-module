"""Exercise the actual compiled graph with controllable model responses, without network."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("langgraph")

from luminary_agent.policies.actions import ActionAvailability
from luminary_agent.policies.agent import FlightAgent, FlightDecision
from luminary_agent.policies.agent_config import AgentConfig
from luminary_agent.sim.observation import Observation


def observation(mode: str = "auto") -> Observation:
    return Observation(
        100,
        mode,
        64,
        6,
        64,
        None,
        None,
        None,
        (),
        500,
        510,
        -2,
        0.5,
        9000,
        7500,
        700,
        action_capabilities=(
            ActionAvailability("hold", True, True),
            ActionAvailability("command", True, mode == "manual", "take_manual first"),
            ActionAvailability("abort", False, False, "ascent physics unavailable"),
        ),
    )


class Model:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.messages: list[Any] = []

    def invoke(self, messages: list[dict[str, str]]) -> Any:
        self.messages.append(messages)
        response = self.responses[min(len(self.messages) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def test_graph_commits_and_records_usage_and_bounded_memory() -> None:
    model = Model(
        {
            "parsed": FlightDecision(
                kind="hold",
                rationale="Guidance is stable.",
                evidence=["Radar altitude 500 m"],
                plan="Check next descent phase.",
            ),
            "raw": SimpleNamespace(usage_metadata={"total_tokens": 25}),
        }
    )
    agent = FlightAgent(AgentConfig(model="fixture", history_size=1), model)
    events: list[dict[str, Any]] = []
    agent.set_event_sink(events.append)
    intent = agent.decide(observation(), 100)
    assert intent.kind == "hold" and intent.valid_until_s == 105
    assert intent.details["path"] == ["observe", "propose", "validate", "commit"]
    assert intent.details["tokens"] == 25
    assert [e["stage"] for e in events] == [
        "observing",
        "planning",
        "proposed",
        "validating",
        "ready",
    ]
    agent.decide(replace(observation(), previous_action="ok"), 100)
    assert len(agent.history) == 1 and agent.calls == 2
    payload = json.loads(model.messages[-1][-1]["content"])
    assert payload["observation"]["previous_action"] == "ok"
    assert len(payload["recent_decisions"]) == 1
    agent.reset()
    assert not agent.history and agent.calls == agent.tokens == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "abort", "rationale": "Abort"},
        {"kind": "command", "params": {"horizontal_ms": 1}, "rationale": "Move"},
        {"kind": "hold", "params": {"bogus": 1}, "rationale": "Wait"},
        {"kind": "hold", "revisit_s": float("nan"), "rationale": "Wait"},
    ],
)
def test_invalid_or_unavailable_proposal_is_repaired(bad: dict[str, Any]) -> None:
    model = Model(bad, {"kind": "hold", "rationale": "Remain with guidance."})
    agent = FlightAgent(AgentConfig(model="fixture"), model)
    intent = agent.decide(observation(), 100)
    assert intent.kind == "hold" and not intent.details["fallback"]
    assert "repair" in intent.details["path"] and agent.calls == 2
    assert json.loads(model.messages[1][-1]["content"])["validation_feedback"]


def test_errors_and_budget_use_explicit_fallback_without_leaking_provider_error() -> None:
    model = Model(RuntimeError("secret-token-in-url"))
    agent = FlightAgent(AgentConfig(model="fixture", max_calls=2), model)
    intent = agent.decide(observation("manual"), 100)
    assert intent.kind == "command" and intent.details["fallback"]
    assert "secret-token" not in json.dumps(intent.details) + intent.rationale
    assert agent.calls == 2
    intent = agent.decide(observation("manual"), 100)
    assert "budget exhausted" in intent.rationale and agent.calls == 2
    assert agent.fallbacks == 2


def test_nonfinite_command_rejected_in_manual() -> None:
    agent = FlightAgent(
        AgentConfig(model="fixture"),
        Model({"kind": "command", "params": {"horizontal_ms": float("inf")}, "rationale": "Move"}),
    )
    assert agent.decide(observation("manual"), 100).details["fallback"]


def test_config_requires_model_and_redacts_endpoint() -> None:
    with pytest.raises(ValueError, match="LUMINARY_MODEL"):
        AgentConfig()
    config = AgentConfig(model="fixture", base_url="https://user:secret@example.test")
    assert "secret" not in json.dumps(config.public())
    assert "base_url" not in config.public()


@pytest.mark.parametrize("provider", ["openai", "anthropic", "ollama"])
def test_installed_provider_adapter_constructs_without_network(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from luminary_agent.policies.agent import build_model

    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    adapter = build_model(AgentConfig(provider=provider, model="fixture"))
    assert callable(adapter.invoke)
