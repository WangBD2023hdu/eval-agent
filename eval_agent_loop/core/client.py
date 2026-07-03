from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AgentConfig
from .errors import AgentLoopError


@dataclass(frozen=True)
class AssistantTurn:
    content: str | None
    tool_calls: list[Any]


class OpenAIChatClient:
    def __init__(self, config: AgentConfig):
        try:
            from openai import OpenAI
            import httpx
        except ImportError as exc:
            raise AgentLoopError("The openai package is required. Install it before running the agent loop.") from exc
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            http_client=httpx.Client(trust_env=False),
        )
        self._config = config

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=self._config.temperature,
        )
        message = response.choices[0].message
        return AssistantTurn(content=message.content, tool_calls=list(message.tool_calls or []))
