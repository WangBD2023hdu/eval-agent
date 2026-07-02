from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .command_tools import run_command
from .errors import AgentLoopError
from .file_tools import append_event, read_file, write_or_append
from .long_commands import inspect_long_command, start_long_command, wait_long_command
from .lmms import extract_lmms_eval_samples
from .omnidocbench import extract_omnidocbench_metrics
from .tool_defs import ALLOWED_ACTIONS, FORBIDDEN_ACTION_WORDS


def parse_model_action(content: str) -> dict[str, Any]:
    text = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentLoopError(f"model response must be a single JSON object: {exc}") from exc
    if not isinstance(action, dict):
        raise AgentLoopError("model response must decode to a JSON object")
    validate_action(action)
    return action


def validate_action(action: dict[str, Any]) -> None:
    name = action.get("action")
    if not isinstance(name, str):
        raise AgentLoopError("action.action must be a string")
    lowered = name.lower()
    if lowered not in ALLOWED_ACTIONS:
        raise AgentLoopError(f"unsupported action: {name}")
    if any(word in lowered for word in FORBIDDEN_ACTION_WORDS):
        raise AgentLoopError(f"simulation-style action is forbidden: {name}")

    if lowered == "run_command":
        _validate_run_command(action)
    if lowered == "start_long_command":
        _validate_start_long_command(action)
    if lowered in {"wait_long_command", "inspect_long_command"}:
        _validate_long_command_lookup(action, lowered)
    if lowered in {"read_file", "write_file", "append_file"}:
        _require_string(action, "path", lowered)
    if lowered in {"write_file", "append_file"} and not isinstance(action.get("content"), str):
        raise AgentLoopError(f"{lowered} requires string content")
    if lowered == "append_event":
        _validate_append_event(action)
    if lowered == "extract_lmms_eval_samples":
        _validate_extract_lmms_eval_samples(action)
    if lowered == "extract_omnidocbench_metrics":
        _validate_extract_omnidocbench_metrics(action)
    if lowered in {"finish", "ask_user"} and not isinstance(action.get("message"), str):
        raise AgentLoopError(f"{lowered} requires message")


def execute_action(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    name = action["action"]
    if name == "run_command":
        return run_command(action, workspace=workspace)
    if name == "start_long_command":
        return start_long_command(action, workspace=workspace)
    if name == "wait_long_command":
        return wait_long_command(action, workspace=workspace)
    if name == "inspect_long_command":
        return inspect_long_command(action, workspace=workspace)
    if name == "read_file":
        return read_file(action)
    if name == "write_file":
        return write_or_append(action, append=False, workspace=workspace)
    if name == "append_file":
        return write_or_append(action, append=True, workspace=workspace)
    if name == "append_event":
        return append_event(action, workspace=workspace)
    if name == "extract_lmms_eval_samples":
        return extract_lmms_eval_samples(action, workspace=workspace)
    if name == "extract_omnidocbench_metrics":
        return extract_omnidocbench_metrics(action, workspace=workspace)
    if name in {"finish", "ask_user"}:
        return {"action": name, "message": action["message"]}
    raise AgentLoopError(f"unreachable action: {name}")


def _validate_run_command(action: dict[str, Any]) -> None:
    _validate_argv_env(action, "run_command")
    timeout = action.get("timeout_sec", 3600)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise AgentLoopError("run_command.timeout_sec must be a positive number")


def _validate_start_long_command(action: dict[str, Any]) -> None:
    _validate_argv_env(action, "start_long_command")
    for key in ("cwd", "command_id", "commands_dir", "log_path", "label", "skill_type"):
        if action.get(key) is not None and not isinstance(action.get(key), str):
            raise AgentLoopError(f"start_long_command.{key} must be a string")
    if action.get("skill_type") not in {None, "inference", "evaluation", "task", "service"}:
        raise AgentLoopError("start_long_command.skill_type must be inference, evaluation, task, or service")


def _validate_long_command_lookup(action: dict[str, Any], action_name: str) -> None:
    _require_string(action, "command_id", action_name)
    for key in ("commands_dir", "metadata_path"):
        if action.get(key) is not None and not isinstance(action.get(key), str):
            raise AgentLoopError(f"{action_name}.{key} must be a string")
    timeout = action.get("timeout_sec", 86400)
    if action_name == "wait_long_command" and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise AgentLoopError("wait_long_command.timeout_sec must be a positive number")


def _validate_argv_env(action: dict[str, Any], action_name: str) -> None:
    argv = action.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise AgentLoopError(f"{action_name} requires argv as a non-empty list of strings")
    if "cmd" in action:
        raise AgentLoopError(f"{action_name} must use argv, not shell command strings")
    env = action.get("env", {})
    if env is not None and not isinstance(env, dict):
        raise AgentLoopError(f"{action_name}.env must be an object")


def _validate_append_event(action: dict[str, Any]) -> None:
    event = action.get("event")
    if not isinstance(event, dict):
        raise AgentLoopError("append_event requires event object")
    _require_string(action, "path", "append_event")


def _validate_extract_lmms_eval_samples(action: dict[str, Any]) -> None:
    text = action.get("text")
    log_path = action.get("log_path")
    if not isinstance(text, str) and not isinstance(log_path, str):
        raise AgentLoopError("extract_lmms_eval_samples requires text or log_path")
    for key in ("cwd", "task"):
        if action.get(key) is not None and not isinstance(action.get(key), str):
            raise AgentLoopError(f"extract_lmms_eval_samples.{key} must be a string")
    require_exists = action.get("require_exists", True)
    if not isinstance(require_exists, bool):
        raise AgentLoopError("extract_lmms_eval_samples.require_exists must be a boolean")


def _validate_extract_omnidocbench_metrics(action: dict[str, Any]) -> None:
    text = action.get("text")
    log_path = action.get("log_path")
    if not isinstance(text, str) and not isinstance(log_path, str):
        raise AgentLoopError("extract_omnidocbench_metrics requires text or log_path")
    for key in ("cwd", "markdown_path"):
        if action.get(key) is not None and not isinstance(action.get(key), str):
            raise AgentLoopError(f"extract_omnidocbench_metrics.{key} must be a string")
    append = action.get("append", True)
    if not isinstance(append, bool):
        raise AgentLoopError("extract_omnidocbench_metrics.append must be a boolean")


def _require_string(action: dict[str, Any], key: str, action_name: str) -> None:
    value = action.get(key)
    if not isinstance(value, str) or not value:
        raise AgentLoopError(f"{action_name} requires {key}")
