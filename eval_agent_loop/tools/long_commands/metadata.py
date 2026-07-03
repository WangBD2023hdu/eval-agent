from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...core.errors import AgentLoopError


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def write_metadata(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AgentLoopError(f"long command metadata does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def result_from_metadata(action_name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    result = {
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
    result["log_tail"] = tail_text(Path(result["log_path"]))
    return result


def tail_text(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
