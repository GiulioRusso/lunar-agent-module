"""Non-secret configuration shared by CLI, evaluation fingerprints and the optional agent."""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    provider: str = "openai"
    model: str = ""
    base_url: str = ""
    request_timeout_s: float = 10.0
    max_calls: int = 200
    max_output_tokens: int = 1200
    history_size: int = 8

    def __post_init__(self) -> None:
        if self.provider not in {"openai", "anthropic", "ollama"}:
            raise ValueError("LUMINARY_PROVIDER must be openai, anthropic, or ollama")
        if not self.model.strip():
            raise ValueError("Set LUMINARY_MODEL to the model served by your selected provider")
        if not 1 <= self.request_timeout_s <= 60:
            raise ValueError("LUMINARY_REQUEST_TIMEOUT_S must be in [1, 60]")
        if not 1 <= self.max_calls <= 2000 or not 64 <= self.max_output_tokens <= 8192:
            raise ValueError("Agent call budget must be 1..2000; output limit must be 64..8192")
        if not 1 <= self.history_size <= 20:
            raise ValueError("Agent history must contain 1..20 decisions")

    @classmethod
    def from_env(cls) -> AgentConfig:
        return cls(
            provider=os.getenv("LUMINARY_PROVIDER", "openai"),
            model=os.getenv("LUMINARY_MODEL", ""),
            base_url=os.getenv("LUMINARY_BASE_URL", ""),
            request_timeout_s=float(os.getenv("LUMINARY_REQUEST_TIMEOUT_S", "10")),
            max_calls=int(os.getenv("LUMINARY_MAX_CALLS", "200")),
            max_output_tokens=int(os.getenv("LUMINARY_MAX_OUTPUT_TOKENS", "1200")),
        )

    def check_credentials(self) -> None:
        import importlib.util

        if importlib.util.find_spec("langgraph") is None:
            raise ValueError("Install agent dependencies with: uv sync --extra agent")
        key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(self.provider)
        if key and not os.getenv(key):
            raise ValueError(f"Set {key} in your local environment (never in the source code)")

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        endpoint = data.pop("base_url")
        data["endpoint_sha256"] = hashlib.sha256(endpoint.encode()).hexdigest()
        return data


def policy_configuration(name: str) -> dict[str, Any]:
    return AgentConfig.from_env().public() if name == "llm" else {}
