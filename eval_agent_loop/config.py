from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import AgentLoopError


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    api_key: str
    model: str = "qwen3-5"
    temperature: float = 0.0
    max_iterations: int = 20

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AgentConfig":
        env = env or os.environ
        base_url = env.get("AGENT_BASE_URL") or env.get("OPENAI_BASE_URL")
        if not base_url:
            raise AgentLoopError("AGENT_BASE_URL or OPENAI_BASE_URL is required; no fallback model is allowed")
        api_key = env.get("AGENT_API_KEY") or env.get("OPENAI_API_KEY") or "EMPTY"
        model = env.get("AGENT_MODEL") or "qwen3-5"
        temperature = float(env.get("AGENT_TEMPERATURE", "0"))
        max_iterations = int(env.get("AGENT_MAX_ITERATIONS", "20"))
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_iterations=max_iterations,
        )
