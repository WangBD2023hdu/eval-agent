from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import Any


Progress = Callable[[str], None]


def stderr_progress(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def format_progress(event: str, **fields: Any) -> str:
    payload = {
        "event": event,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **{key: value for key, value in fields.items() if value is not None},
    }
    return "[eval-agent] " + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def emit(progress: Progress | None, event: str, **fields: Any) -> None:
    if progress is None:
        return
    progress(format_progress(event, **fields))
