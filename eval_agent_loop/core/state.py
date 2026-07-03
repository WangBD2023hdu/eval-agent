from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import AgentLoopError
from .path_policy import resolve_write_path


def load_structured_file(path: str | Path) -> Any:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() == ".json":
        return json.loads(text)
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_exc:
        try:
            return _load_yaml(text)
        except Exception as yaml_exc:  # pragma: no cover - depends on PyYAML errors
            raise AgentLoopError(f"failed to parse structured file {file_path}: {json_exc}") from yaml_exc


def read_state(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"status": "new", "history": []}
    state_path = Path(path)
    if not state_path.exists():
        return {"status": "new", "history": []}
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_state(path: str | Path | None, state: dict[str, Any], *, workspace: Path | None = None) -> None:
    if not path:
        return
    state_path = resolve_write_path(path, workspace=workspace, field="state_path") if workspace else Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise AgentLoopError("PyYAML is required to read YAML job files") from exc
    return yaml.safe_load(text)
