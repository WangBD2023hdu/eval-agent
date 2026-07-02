from __future__ import annotations

import json
from typing import Any

from .actions import validate_action
from .errors import AgentLoopError


def build_messages(
    *,
    skills: dict[str, str],
    job: Any,
    state: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    system = """You are an evaluation agent controller.

You must follow the provided inference, evaluation, and task skills.
Do not simulate, fake, mock, or invent inference outputs, benchmark metrics, files, logs, or command results.
Use the provided tools. Do not describe a tool call in prose when you can call the tool.
Use run_command only for real commands. Use read_file only for real files.
All agent-managed writes must stay inside the workspace write root. Use report/output paths under the workspace.
Use start_long_command plus wait_long_command for long-running inference, evaluation, benchmark, or service processes.
Use inspect_long_command to recover persisted status and log tails for an existing long command.
Tool calls returned in the same assistant turn are executed concurrently; only batch independent calls.
Put dependent calls, GPU-contending calls, and terminal finish/ask_user calls in separate turns.
If a required value is missing, call ask_user. When the job is complete, call finish.
"""
    payload = {
        "skills": skills,
        "job": job,
        "state": state,
        "recent_events": events[-20:],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)},
    ]


def tool_call_to_message(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": getattr(tool_call, "type", "function"),
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def parse_tool_call(tool_call: Any) -> dict[str, Any]:
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError as exc:
        raise AgentLoopError(f"tool call arguments must be JSON for {tool_call.function.name}: {exc}") from exc
    if not isinstance(arguments, dict):
        raise AgentLoopError(f"tool call arguments must decode to an object for {tool_call.function.name}")
    action = {"action": tool_call.function.name, **arguments}
    validate_action(action)
    return action
