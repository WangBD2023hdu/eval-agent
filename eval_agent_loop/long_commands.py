from __future__ import annotations

import json
import os
import subprocess
import threading
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AgentLoopError
from .path_policy import resolve_write_path


TERMINAL_STATUSES = {"succeeded", "failed"}
_COMMANDS: dict[str, "LongCommandHandle"] = {}


@dataclass
class LongCommandHandle:
    process: subprocess.Popen[str]
    done: threading.Event
    metadata_path: Path
    log_path: Path


def start_long_command(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    cwd = Path(action.get("cwd") or workspace)
    command_id = action.get("command_id") or _new_command_id()
    command_dir = _command_dir(action, workspace=workspace, command_id=command_id)
    command_dir.mkdir(parents=True, exist_ok=False)

    log_path = _resolve_log_path(action.get("log_path"), workspace=workspace, command_dir=command_dir)
    metadata_path = command_dir / "status.json"
    spec_path = command_dir / "spec.json"
    metadata = {
        "action": "long_command",
        "command_id": command_id,
        "argv": action["argv"],
        "cwd": str(cwd),
        "label": action.get("label"),
        "skill_type": action.get("skill_type"),
        "pid": None,
        "supervisor_pid": None,
        "status": "starting",
        "returncode": None,
        "signal": None,
        "started_at": _utc_now(),
        "ended_at": None,
        "log_path": str(log_path),
        "metadata_path": str(metadata_path),
        "spec_path": str(spec_path),
    }
    _write_json(metadata_path, metadata)
    _write_json(
        spec_path,
        {
            "argv": action["argv"],
            "cwd": str(cwd),
            "env": action.get("env", {}),
            "log_path": str(log_path),
            "metadata_path": str(metadata_path),
        },
    )

    supervisor_env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[1])
    supervisor_env["PYTHONPATH"] = project_root + os.pathsep + supervisor_env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "eval_agent_loop.long_command_supervisor", str(spec_path)],
        cwd=project_root,
        env=supervisor_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    done = threading.Event()
    handle = LongCommandHandle(process=process, done=done, metadata_path=metadata_path, log_path=log_path)
    _COMMANDS[command_id] = handle
    threading.Thread(
        target=_watch_process,
        args=(command_id, handle),
        name=f"long-command-{command_id}",
        daemon=True,
    ).start()

    metadata = _wait_for_started_metadata(metadata_path, timeout_sec=5)
    return _result_from_metadata("start_long_command", metadata)


def wait_long_command(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    command_id = action["command_id"]
    handle = _COMMANDS.get(command_id)
    timeout_sec = float(action.get("timeout_sec", 86400))
    if handle is None:
        metadata = _read_json(_metadata_path(action, workspace=workspace))
        if metadata.get("status") in TERMINAL_STATUSES:
            return _result_from_metadata("wait_long_command", metadata)
        metadata = _wait_for_terminal_metadata(metadata_path=Path(metadata["metadata_path"]), timeout_sec=timeout_sec)
        result = _result_from_metadata("wait_long_command", metadata)
        if metadata.get("status") not in TERMINAL_STATUSES:
            result["timed_out"] = True
        return result

    if not handle.done.wait(timeout=timeout_sec):
        result = _result_from_metadata("wait_long_command", _read_json(handle.metadata_path))
        result["timed_out"] = True
        return result
    return _result_from_metadata("wait_long_command", _read_json(handle.metadata_path))


def inspect_long_command(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    return _result_from_metadata("inspect_long_command", _read_json(_metadata_path(action, workspace=workspace)))


def _watch_process(command_id: str, handle: LongCommandHandle) -> None:
    handle.process.wait()
    handle.done.set()


def _result_from_metadata(action_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return _with_tail(
        {
            "action": action_name,
            "command_id": metadata["command_id"],
            "status": metadata["status"],
            "returncode": metadata.get("returncode"),
            "signal": metadata.get("signal"),
            "pid": metadata.get("pid"),
            "supervisor_pid": metadata.get("supervisor_pid"),
            "label": metadata.get("label"),
            "skill_type": metadata.get("skill_type"),
            "cwd": metadata.get("cwd"),
            "started_at": metadata.get("started_at"),
            "ended_at": metadata.get("ended_at"),
            "log_path": metadata["log_path"],
            "metadata_path": metadata["metadata_path"],
            "spec_path": metadata.get("spec_path"),
        }
    )


def _with_tail(result: dict[str, Any]) -> dict[str, Any]:
    result["log_tail"] = _tail_text(Path(result["log_path"]))
    return result


def _tail_text(path: Path, max_bytes: int = 20000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")


def _metadata_path(action: dict[str, Any], *, workspace: Path) -> Path:
    if isinstance(action.get("metadata_path"), str):
        return Path(action["metadata_path"])
    return _command_dir(action, workspace=workspace, command_id=action["command_id"]) / "status.json"


def _command_dir(action: dict[str, Any], *, workspace: Path, command_id: str) -> Path:
    commands_dir = resolve_write_path(
        action.get("commands_dir") or workspace / ".eval_agent" / "commands",
        workspace=workspace,
        field="start_long_command.commands_dir",
    )
    return resolve_write_path(commands_dir / command_id, workspace=workspace, field="start_long_command.command_dir")


def _resolve_log_path(value: Any, *, workspace: Path, command_dir: Path) -> Path:
    if not isinstance(value, str) or not value:
        return resolve_write_path(command_dir / "output.log", workspace=workspace, field="start_long_command.log_path")
    path = Path(value)
    if not path.is_absolute():
        path = command_dir / path
    return resolve_write_path(path, workspace=workspace, field="start_long_command.log_path")


def _resolve_optional_path(value: Any, *, default: Path, base: Path) -> Path:
    if not isinstance(value, str) or not value:
        return default
    path = Path(value)
    if path.is_absolute():
        return path
    return base / path


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AgentLoopError(f"long command metadata does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_for_started_metadata(metadata_path: Path, *, timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last = _read_json(metadata_path)
    while time.monotonic() < deadline:
        last = _read_json(metadata_path)
        if last.get("status") != "starting" or last.get("pid") is not None:
            return last
        time.sleep(0.05)
    return last


def _wait_for_terminal_metadata(metadata_path: Path, *, timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last = _read_json(metadata_path)
    while time.monotonic() < deadline:
        last = _read_json(metadata_path)
        if last.get("status") in TERMINAL_STATUSES:
            return last
        time.sleep(0.25)
    return last


def _new_command_id() -> str:
    return f"cmd_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:8]}"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
