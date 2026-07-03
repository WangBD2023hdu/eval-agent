from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.path_policy import resolve_write_path


def command_dir(action: dict[str, Any], *, workspace: Path, command_id: str) -> Path:
    commands_root = resolve_write_path(
        action.get("commands_dir") or workspace / ".eval_agent" / "commands",
        workspace=workspace,
        field="start_long_command.commands_dir",
    )
    return resolve_write_path(commands_root / command_id, workspace=workspace, field="start_long_command.command_dir")


def metadata_path(action: dict[str, Any], *, workspace: Path) -> Path:
    if isinstance(action.get("metadata_path"), str):
        return Path(action["metadata_path"])
    return command_dir(action, workspace=workspace, command_id=action["command_id"]) / "status.json"


def resolve_log_path(value: Any, *, workspace: Path, command_dir_path: Path) -> Path:
    if not isinstance(value, str) or not value:
        return resolve_write_path(command_dir_path / "output.log", workspace=workspace, field="start_long_command.log_path")
    path = Path(value)
    if not path.is_absolute():
        path = command_dir_path / path
    return resolve_write_path(path, workspace=workspace, field="start_long_command.log_path")
