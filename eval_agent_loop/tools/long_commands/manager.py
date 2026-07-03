from __future__ import annotations

import os
import signal
import subprocess
import threading
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.progress import Progress, emit
from .metadata import TERMINAL_STATUSES, read_metadata, result_from_metadata, write_metadata
from .paths import command_dir, metadata_path, resolve_log_path


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
    command_dir_path = command_dir(action, workspace=workspace, command_id=command_id)
    command_dir_path.mkdir(parents=True, exist_ok=False)

    log_path = resolve_log_path(action.get("log_path"), workspace=workspace, command_dir_path=command_dir_path)
    status_path = command_dir_path / "status.json"
    spec_path = command_dir_path / "spec.json"
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
        "metadata_path": str(status_path),
        "spec_path": str(spec_path),
    }
    write_metadata(status_path, metadata)
    write_metadata(
        spec_path,
        {
            "argv": action["argv"],
            "cwd": str(cwd),
            "env": action.get("env", {}),
            "log_path": str(log_path),
            "metadata_path": str(status_path),
        },
    )

    supervisor_env = os.environ.copy()
    project_root = str(Path(__file__).resolve().parents[3])
    supervisor_env["PYTHONPATH"] = project_root + os.pathsep + supervisor_env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "eval_agent_loop.tools.long_commands.supervisor", str(spec_path)],
        cwd=project_root,
        env=supervisor_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    done = threading.Event()
    handle = LongCommandHandle(process=process, done=done, metadata_path=status_path, log_path=log_path)
    _COMMANDS[command_id] = handle
    threading.Thread(
        target=_watch_process,
        args=(handle,),
        name=f"long-command-{command_id}",
        daemon=True,
    ).start()

    metadata = _wait_for_started_metadata(status_path, timeout_sec=5)
    return result_from_metadata("start_long_command", metadata)


def wait_long_command(action: dict[str, Any], *, workspace: Path, progress: Progress | None = None) -> dict[str, Any]:
    command_id = action["command_id"]
    handle = _COMMANDS.get(command_id)
    timeout_sec = float(action.get("timeout_sec", 86400))
    heartbeat_sec = float(action.get("heartbeat_sec", 30))
    if handle is None:
        metadata = read_metadata(metadata_path(action, workspace=workspace))
        if metadata.get("status") in TERMINAL_STATUSES:
            return result_from_metadata("wait_long_command", metadata)
        metadata = _wait_for_terminal_metadata(
            metadata_path=Path(metadata["metadata_path"]),
            timeout_sec=timeout_sec,
            heartbeat_sec=heartbeat_sec,
            progress=progress,
        )
        result = result_from_metadata("wait_long_command", metadata)
        if metadata.get("status") not in TERMINAL_STATUSES:
            result["timed_out"] = True
        return result

    if not _wait_for_handle(handle, command_id=command_id, timeout_sec=timeout_sec, heartbeat_sec=heartbeat_sec, progress=progress):
        result = result_from_metadata("wait_long_command", read_metadata(handle.metadata_path))
        result["timed_out"] = True
        return result
    return result_from_metadata("wait_long_command", read_metadata(handle.metadata_path))


def inspect_long_command(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    return result_from_metadata("inspect_long_command", read_metadata(metadata_path(action, workspace=workspace)))


def cancel_active_long_commands(*, grace_sec: float = 5) -> list[dict[str, Any]]:
    cancelled: list[dict[str, Any]] = []
    for command_id, handle in list(_COMMANDS.items()):
        metadata = read_metadata(handle.metadata_path)
        if metadata.get("status") in TERMINAL_STATUSES:
            cancelled.append(result_from_metadata("cancel_long_command", metadata))
            continue

        used_signal = "SIGTERM"
        _terminate_process_group(handle.process.pid, signal.SIGTERM)
        deadline = time.monotonic() + max(grace_sec, 0)
        while handle.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)

        if handle.process.poll() is None:
            used_signal = "SIGKILL"
            _terminate_process_group(handle.process.pid, signal.SIGKILL)
            try:
                handle.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

        metadata = read_metadata(handle.metadata_path)
        metadata.update(
            {
                "ended_at": _utc_now(),
                "returncode": handle.process.returncode,
                "signal": used_signal,
                "status": "cancelled",
            }
        )
        write_metadata(handle.metadata_path, metadata)
        handle.done.set()
        cancelled.append(result_from_metadata("cancel_long_command", metadata))
    return cancelled


def _watch_process(handle: LongCommandHandle) -> None:
    handle.process.wait()
    handle.done.set()


def _wait_for_started_metadata(metadata_path: Path, *, timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last = read_metadata(metadata_path)
    while time.monotonic() < deadline:
        last = read_metadata(metadata_path)
        if last.get("status") != "starting" or last.get("pid") is not None:
            return last
        time.sleep(0.05)
    return last


def _wait_for_handle(
    handle: LongCommandHandle,
    *,
    command_id: str,
    timeout_sec: float,
    heartbeat_sec: float,
    progress: Progress | None,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if handle.done.wait(timeout=min(max(heartbeat_sec, 0.01), remaining)):
            return True
        metadata = read_metadata(handle.metadata_path)
        emit(
            progress,
            "long_command_wait",
            command_id=command_id,
            status=metadata.get("status"),
            log_path=metadata.get("log_path"),
            metadata_path=str(handle.metadata_path),
        )


def _wait_for_terminal_metadata(
    metadata_path: Path,
    *,
    timeout_sec: float,
    heartbeat_sec: float,
    progress: Progress | None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last = read_metadata(metadata_path)
    next_emit = time.monotonic()
    while time.monotonic() < deadline:
        last = read_metadata(metadata_path)
        if last.get("status") in TERMINAL_STATUSES:
            return last
        now = time.monotonic()
        if now >= next_emit:
            emit(
                progress,
                "long_command_wait",
                command_id=last.get("command_id"),
                status=last.get("status"),
                log_path=last.get("log_path"),
                metadata_path=str(metadata_path),
            )
            next_emit = now + max(heartbeat_sec, 0.01)
        time.sleep(min(0.25, max(heartbeat_sec, 0.01), max(deadline - now, 0.01)))
    return last


def _terminate_process_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except ProcessLookupError:
        return


def _new_command_id() -> str:
    return f"cmd_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{uuid.uuid4().hex[:8]}"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
