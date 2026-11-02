"""LangGraph flight supervisor: observe -> propose -> validate -> repair/commit/fallback.

The graph never mutates the spacecraft. Its only product is a validated Intent. Operational
summaries are observable; provider reasoning content and secrets are neither requested nor logged.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from luminary_agent.policies.actions import ACTION_SPECS
from luminary_agent.policies.agent_config import AgentConfig
from luminary_agent.policies.base import Intent, command, validate_intent
from luminary_agent.policies.scripted import ScriptedAgent
from luminary_agent.sim.observation import Observation

SYSTEM_PROMPT = """You supervise a simulated lunar lander running Luminary guidance.
Return one structured decision. Your only spacecraft access is through the listed available actions.
Never claim an unsupported maneuver works. Hold preserves the existing controller and targets.
Take_manual is operationally irreversible with the current backend. Command works only in manual.
Positive vertical velocity is up; descent targets are negative.
Target_downrange_m and target_cross_m are the LANDER'S offsets from the nominal target.
Correcting a positive offset requires negative
velocity on that axis. Horizontal and cross velocities are relative to the surface. Do not confuse
cross position with cross velocity. Manual targets are clamped to [-6,0] vertically and [-5,5] on
each horizontal axis; they share thrust and tilt limits. None vertical target selects the default
altitude-based descent schedule. Avoid long hovering that exhausts fuel; slow and arrest horizontal
motion before touchdown. A soft landing requires <=3 m/s vertical and <=1.2 m/s total horizontal
speed with fuel remaining. Mission success additionally requires <=100m target error, safe terrain
and acceptable slope. The ideal-state instruments and faulted radar are explicitly labelled.
Assess fuel, radar/AGC disagreement, visible target and hazards using the observation
and recent history. Prefer automatic guidance while appropriate.
Intervene when evidence supports it.
Check actual previous execution results; a submitted DSKY key is not a confirmed maneuver.
A deterministic safety monitor can override you. Use only currently AVAILABLE capabilities.
Provide a concise operational rationale, factual evidence, risks and next-step plan for the user;
do not provide private chain-of-thought. Do not invent observations, predictions or actions.
Choose a revisit interval between 0.5 and 30 simulated seconds; events can trigger earlier calls.
"""


class FlightDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "hold",
        "take_manual",
        "command",
        "return_auto",
        "select_p66",
        "adjust_rod",
        "redesignate",
        "abort",
        "dsky_key",
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    revisit_s: float = Field(default=5, ge=0.5, le=30, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=4)
    risks: list[str] = Field(default_factory=list, max_length=3)
    plan: str = Field(default="", max_length=400)


class StructuredModel(Protocol):
    def invoke(self, messages: list[dict[str, str]]) -> Any: ...


class AgentState(TypedDict, total=False):
    obs: Observation
    proposal: FlightDecision
    intent: Intent
    attempt: int
    error: str
    path: list[str]


def build_model(config: AgentConfig) -> StructuredModel:
    """Provider clients are lazy; baseline simulations need none of these dependencies."""
    model: Any
    if config.provider == "openai":
        from langchain_openai import ChatOpenAI

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Set OPENAI_API_KEY for the OpenAI-compatible endpoint")
        kwargs: dict[str, Any] = {
            "model": config.model,
            "timeout": config.request_timeout_s,
            "max_retries": 0,
            "max_tokens": config.max_output_tokens,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        model = ChatOpenAI(**kwargs)
        return cast(
            StructuredModel,
            model.with_structured_output(
                FlightDecision, method="function_calling", include_raw=True
            ),
        )
    if config.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("Set ANTHROPIC_API_KEY for Anthropic")
        kwargs = {
            "model_name": config.model,
            "timeout": config.request_timeout_s,
            "max_retries": 0,
            "max_tokens": config.max_output_tokens,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        model = ChatAnthropic(**kwargs)
    else:
        from langchain_ollama import ChatOllama

        kwargs = {
            "model": config.model,
            "num_predict": config.max_output_tokens,
            "client_kwargs": {"timeout": config.request_timeout_s},
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        model = ChatOllama(**kwargs)
    return cast(StructuredModel, model.with_structured_output(FlightDecision, include_raw=True))


class FlightAgent:
    name = "llm"

    def __init__(
        self, config: AgentConfig | None = None, model: StructuredModel | None = None
    ) -> None:
        self.settings = config or AgentConfig.from_env()
        self.config = self.settings.public() | {
            "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "workflow": "observe-propose-validate-repair-fallback-v1",
        }
        self.decision_timeout_s = 2 * self.settings.request_timeout_s + 5
        self.model = model if model is not None else build_model(self.settings)
        self._sink: Callable[[dict[str, Any]], None] | None = None
        self.reset()
        graph = StateGraph(AgentState)
        graph.add_node("observe", self._observe)
        graph.add_node("propose", self._propose)
        graph.add_node("validate", self._validate)
        graph.add_node("commit", self._commit)
        graph.add_node("fallback", self._fallback)
        graph.add_edge(START, "observe")
        graph.add_edge("observe", "propose")
        graph.add_edge("propose", "validate")
        graph.add_conditional_edges(
            "validate",
            self._route,
            {"repair": "propose", "commit": "commit", "fallback": "fallback"},
        )
        graph.add_edge("commit", END)
        graph.add_edge("fallback", END)
        self.graph = graph.compile()

    def reset(self) -> None:
        self.calls = 0
        self.tokens = 0
        self.fallbacks = 0
        self.history: list[dict[str, Any]] = []

    def set_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        self._sink = sink

    def _event(self, state: AgentState, stage: str, summary: str) -> None:
        if self._sink is not None:
            self._sink(
                {
                    "t": state["obs"].t_s,
                    "stage": stage,
                    "summary": summary,
                    "model": self.settings.model,
                    "calls": self.calls,
                    "tokens": self.tokens,
                }
            )

    def _observe(self, state: AgentState) -> dict[str, Any]:
        self._event(
            state, "observing", "Checking instruments, capabilities and previous execution."
        )
        return {"path": ["observe"], "attempt": 0, "error": ""}

    def _propose(self, state: AgentState) -> dict[str, Any]:
        attempt = state["attempt"] + 1
        path = state["path"] + ["propose" if attempt == 1 else "repair"]
        if self.calls >= self.settings.max_calls:
            return {"attempt": attempt, "path": path, "error": "model call budget exhausted"}
        obs = state["obs"]
        payload = {
            "observation": obs.to_dict(),
            "recent_decisions": self.history,
            "action_catalog": {name: asdict(spec) for name, spec in ACTION_SPECS.items()},
            "validation_feedback": state.get("error", ""),
        }
        self.calls += 1
        self._event(
            state,
            "planning" if attempt == 1 else "repairing",
            "Requesting a flight decision." if attempt == 1 else "Repairing a rejected proposal.",
        )
        try:
            reply = self.model.invoke(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, allow_nan=False)},
                ]
            )
            if isinstance(reply, dict) and "parsed" in reply:
                raw = reply.get("raw")
                usage = getattr(raw, "usage_metadata", None) or {}
                self.tokens += int(usage.get("total_tokens", 0))
                parsed = reply["parsed"]
                if reply.get("parsing_error") or parsed is None:
                    raise ValueError("structured response parsing failed")
            else:
                parsed = reply
            proposal = FlightDecision.model_validate(parsed)
            if any(len(item) > 200 for item in proposal.evidence + proposal.risks):
                raise ValueError("evidence/risk item exceeds 200 characters")
            self._event(state, "proposed", json.dumps(proposal.model_dump(), allow_nan=False))
            return {"proposal": proposal, "attempt": attempt, "path": path, "error": ""}
        except Exception as exc:
            # Provider exception text may contain headers, URLs or raw model content. Do not log it.
            return {
                "attempt": attempt,
                "path": path,
                "error": f"model response failed ({type(exc).__name__})",
            }

    def _validate(self, state: AgentState) -> dict[str, Any]:
        self._event(
            state,
            "validating",
            "Checking the proposal against action schemas and current capabilities.",
        )
        update: dict[str, Any] = {"path": state["path"] + ["validate"]}
        if state.get("error"):
            return update
        proposal, obs = state["proposal"], state["obs"]
        try:
            intent = validate_intent(
                Intent(
                    proposal.kind, proposal.params, obs.t_s + proposal.revisit_s, proposal.rationale
                ),
                obs.t_s,
            )
            capability = next((c for c in obs.action_capabilities if c.action == intent.kind), None)
            if capability is None or not capability.available or not capability.supported:
                raise ValueError(
                    "action unavailable: " + (capability.reason if capability else "not advertised")
                )
            update["intent"] = intent
        except ValueError as exc:
            update["error"] = str(exc)
            self._event(state, "rejected", str(exc))
        return update

    def _route(self, state: AgentState) -> str:
        if not state.get("error"):
            return "commit"
        return (
            "repair"
            if state["attempt"] < 2 and self.calls < self.settings.max_calls
            else "fallback"
        )

    def _details(self, state: AgentState, fallback: bool) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "provider": self.settings.provider,
            "path": state["path"] + ["fallback" if fallback else "commit"],
            "calls": self.calls,
            "tokens": self.tokens,
            "attempts": state["attempt"],
            "fallback": fallback,
            "error": state.get("error", ""),
        }

    def _commit(self, state: AgentState) -> dict[str, Any]:
        proposal, intent = state["proposal"], state["intent"]
        intent.details = self._details(state, False) | {
            "evidence": proposal.evidence,
            "risks": proposal.risks,
            "plan": proposal.plan,
        }
        self._event(state, "ready", "Validated proposal ready for the deterministic executor.")
        return {"intent": intent}

    def _fallback(self, state: AgentState) -> dict[str, Any]:
        obs = state["obs"]
        intent = (
            command(obs.t_s + 5) if obs.mode == "manual" else ScriptedAgent().decide(obs, obs.t_s)
        )
        intent.rationale = "Deterministic fallback: " + state["error"]
        intent.details = self._details(state, True)
        self.fallbacks += 1
        self._event(state, "fallback", intent.rationale)
        return {"intent": intent}

    def decide(self, obs: Observation, t_s: float) -> Intent:
        if abs(obs.t_s - t_s) > 1e-6:
            raise ValueError("observation time must match decision time")
        result = self.graph.invoke({"obs": obs}, {"recursion_limit": 12})
        intent: Intent = result["intent"]
        self.history.append(
            {
                "t_s": t_s,
                "action": intent.kind,
                "params": dict(intent.params),
                "rationale": intent.rationale,
                "plan": intent.details.get("plan", ""),
                "previous_execution": obs.previous_action,
            }
        )
        self.history = self.history[-self.settings.history_size :]
        return intent
