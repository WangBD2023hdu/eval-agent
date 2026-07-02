from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .path_policy import resolve_write_path


def read_file(action: dict[str, Any]) -> dict[str, Any]:
    max_bytes = int(action.get("max_bytes", 20000))
    data = Path(action["path"]).read_bytes()
    return {
        "action": "read_file",
        "path": action["path"],
        "content": data[:max_bytes].decode("utf-8", errors="replace"),
    }


def write_or_append(action: dict[str, Any], *, append: bool, workspace: Path) -> dict[str, Any]:
    path = resolve_write_path(action["path"], workspace=workspace, field=f"{action['action']}.path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as f:
            f.write(action["content"])
    else:
        path.write_text(action["content"], encoding="utf-8")
    return {
        "action": action["action"],
        "path": str(path),
        "bytes": len(action["content"].encode("utf-8")),
    }


def append_event(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    path = resolve_write_path(action["path"], workspace=workspace, field="append_event.path")
    path.parent.mkdir(parents=True, exist_ok=True)
    event = dict(action["event"])
    event.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return {"action": "append_event", "path": str(path), "event": event}
