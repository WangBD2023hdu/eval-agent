from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def run_command(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    cwd = Path(action.get("cwd") or workspace)
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in action.get("env", {}).items()})
    completed = subprocess.run(
        action["argv"],
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=float(action.get("timeout_sec", 3600)),
        check=False,
    )
    return {
        "action": "run_command",
        "returncode": completed.returncode,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-20000:],
    }
