from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .actions import execute_action, parse_model_action
from .client import OpenAIChatClient
from .config import AgentConfig
from .errors import AgentLoopError
from .messages import build_messages, tool_call_to_message
from .progress import Progress, emit
from .skills import load_skill_bundle
from .state import load_structured_file, read_state, write_state
from .tool_execution import execute_tool_call_batch
from .tool_defs import build_tools


def run_loop(
    *,
    client: OpenAIChatClient,
    config: AgentConfig,
    skills_dir: Path,
    job_path: Path,
    state_path: Path | None,
    workspace: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    emit(progress, "agent_start", job_path=str(job_path), skills_dir=str(skills_dir), state_path=str(state_path) if state_path else None, workspace=str(workspace))
    skills = load_skill_bundle(skills_dir)
    job = load_structured_file(job_path)
    state = read_state(state_path)
    events = state.get("history", [])
    if not isinstance(events, list):
        events = []

    tools = build_tools()
    messages: list[dict[str, Any]] = build_messages(skills=skills, job=job, state=state, events=events)
    emit(progress, "context_loaded", skills=sorted(skills), history_count=len(events), tool_count=len(tools))
    iteration = 0
    while iteration < config.max_iterations:
        iteration += 1
        emit(progress, "model_request", iteration=iteration, model=config.model, message_count=len(messages))
        assistant_turn = client.complete(messages, tools)
        emit(progress, "model_response", iteration=iteration, tool_call_count=len(assistant_turn.tool_calls), has_content=bool(assistant_turn.content))

        if assistant_turn.tool_calls:
            tool_names = [tool_call.function.name for tool_call in assistant_turn.tool_calls]
            emit(progress, "tool_batch_start", iteration=iteration, tools=tool_names)
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_turn.content,
                    "tool_calls": [tool_call_to_message(tool_call) for tool_call in assistant_turn.tool_calls],
                }
            )
            executions = execute_tool_call_batch(assistant_turn.tool_calls, workspace=workspace, progress=progress)
            for execution in executions:
                emit(
                    progress,
                    "tool_result",
                    iteration=iteration,
                    tool=execution.action["action"],
                    status=execution.result.get("status"),
                    returncode=execution.result.get("returncode"),
                    command_id=execution.result.get("command_id"),
                    log_path=execution.result.get("log_path"),
                )
                record = _record(
                    iteration=iteration,
                    action=execution.action,
                    result=execution.result,
                    tool_call_id=execution.tool_call.id,
                )
                events.append(record)
                state["status"] = execution.result["action"]
                state["history"] = events
                write_state(state_path, state, workspace=workspace)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": execution.tool_call.id,
                        "content": json.dumps(execution.result, ensure_ascii=False, sort_keys=True),
                    }
                )
                if execution.result["action"] in {"finish", "ask_user"}:
                    emit(progress, "agent_stop", reason=execution.result["action"], iteration=iteration)
                    return execution.result
            continue

        if not assistant_turn.content:
            raise AgentLoopError("model returned no tool calls and no content")

        action = parse_model_action(assistant_turn.content)
        emit(progress, "content_action_start", iteration=iteration, action=action["action"])
        result = execute_action(action, workspace=workspace, progress=progress)
        emit(progress, "tool_result", iteration=iteration, tool=result["action"], status=result.get("status"), returncode=result.get("returncode"), command_id=result.get("command_id"), log_path=result.get("log_path"))
        events.append(_record(iteration=iteration, action=action, result=result))
        state["status"] = result["action"]
        state["history"] = events
        write_state(state_path, state, workspace=workspace)
        messages.append({"role": "assistant", "content": assistant_turn.content})
        if result["action"] in {"finish", "ask_user"}:
            emit(progress, "agent_stop", reason=result["action"], iteration=iteration)
            return result

    emit(progress, "agent_error", reason="max_iterations", max_iterations=config.max_iterations)
    raise AgentLoopError(f"max iterations reached without finish or ask_user: {config.max_iterations}")


def _record(
    *,
    iteration: int,
    action: dict[str, Any],
    result: dict[str, Any],
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    record = {
        "iteration": iteration,
        "action": action,
        "result": result,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if tool_call_id:
        record["tool_call_id"] = tool_call_id
    return record
