from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: long_command_supervisor SPEC_PATH\n")
        return 2

    spec_path = Path(args[0])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    metadata_path = Path(spec["metadata_path"])
    log_path = Path(spec["log_path"])

    try:
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in spec.get("env", {}).items()})
        process = subprocess.Popen(
            spec["argv"],
            cwd=spec["cwd"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        _update_metadata(
            metadata_path,
            {
                "pid": process.pid,
                "supervisor_pid": os.getpid(),
                "status": "running",
                "started_at": _utc_now(),
            },
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
            if process.stdout is not None:
                for line in process.stdout:
                    log_file.write(line)
        returncode = process.wait()
        _update_metadata(
            metadata_path,
            {
                "ended_at": _utc_now(),
                "returncode": returncode,
                "signal": _signal_name(returncode),
                "status": "succeeded" if returncode == 0 else "failed",
            },
        )
        return 0 if returncode == 0 else 1
    except Exception as exc:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[long-command-supervisor] failed: {exc}\n")
        _update_metadata(
            metadata_path,
            {
                "ended_at": _utc_now(),
                "error": str(exc),
                "returncode": None,
                "signal": None,
                "status": "failed",
                "supervisor_pid": os.getpid(),
            },
        )
        return 1


def _update_metadata(path: Path, updates: dict[str, Any]) -> None:
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _signal_name(returncode: int) -> str | None:
    if returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"SIG{returncode * -1}"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
