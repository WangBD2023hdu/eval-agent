from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actions import execute_action
from .errors import AgentLoopError
from .messages import parse_tool_call
from .progress import Progress


TERMINAL_ACTIONS = {"finish", "ask_user"}


@dataclass(frozen=True)
class ToolExecution:
    tool_call: Any
    action: dict[str, Any]
    result: dict[str, Any]


def execute_tool_call_batch(
    tool_calls: list[Any],
    *,
    workspace: Path,
    progress: Progress | None = None,
    max_workers: int | None = None,
) -> list[ToolExecution]:
    actions = [parse_tool_call(tool_call) for tool_call in tool_calls]
    _validate_batch(actions)
    if not actions:
        return []

    worker_count = max_workers or len(actions)
    with ThreadPoolExecutor(max_workers=max(1, worker_count)) as executor:
        futures = [
            executor.submit(execute_action, action, workspace=workspace, progress=progress)
            for action in actions
        ]
        results: list[ToolExecution] = []
        for tool_call, action, future in zip(tool_calls, actions, futures):
            try:
                result = future.result()
            except Exception as exc:
                raise AgentLoopError(
                    f"tool call {tool_call.function.name} failed for id {tool_call.id}: {exc}"
                ) from exc
            results.append(ToolExecution(tool_call=tool_call, action=action, result=result))
    return results


def _validate_batch(actions: list[dict[str, Any]]) -> None:
    terminal_actions = [action for action in actions if action["action"] in TERMINAL_ACTIONS]
    if terminal_actions and len(actions) > 1:
        names = ", ".join(action["action"] for action in terminal_actions)
        raise AgentLoopError(f"terminal action(s) must be the only tool call in a turn: {names}")
