from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import AgentLoopError


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LMMS_RESULTS_RE = re.compile(r"Results saved in\s+(.+?\.jsonl)")


def extract_lmms_eval_samples(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    cwd = Path(action.get("cwd") or workspace)
    text_parts: list[str] = []
    if isinstance(action.get("text"), str):
        text_parts.append(action["text"])
    if isinstance(action.get("log_path"), str):
        log_path = Path(action["log_path"])
        if not log_path.is_absolute():
            log_path = cwd / log_path
        text_parts.append(log_path.read_text(encoding="utf-8", errors="replace"))

    clean_text = ANSI_ESCAPE_RE.sub("", "\n".join(text_parts))
    matches = LMMS_RESULTS_RE.findall(clean_text)
    if not matches:
        raise AgentLoopError("could not find 'Results saved in ...jsonl' in LMMS Eval output")

    raw_path = matches[-1].strip().strip("'\"")
    path_for_state = raw_path[2:] if raw_path.startswith("./") else raw_path
    artifact_path = Path(raw_path)
    if not artifact_path.is_absolute():
        artifact_path = cwd / artifact_path
    artifact_path = artifact_path.resolve()

    if action.get("require_exists", True) and not artifact_path.exists():
        raise AgentLoopError(f"LMMS Eval samples artifact does not exist: {artifact_path}")

    task = action.get("task") or infer_lmms_task_from_samples_path(path_for_state)
    next_skill_input = {
        "prediction_jsonl": str(artifact_path),
        "samples_jsonl": str(artifact_path),
        "samples_jsonl_relative": path_for_state,
    }
    if task:
        next_skill_input["task"] = task

    return {
        "action": "extract_lmms_eval_samples",
        "samples_jsonl": path_for_state,
        "samples_jsonl_abs": str(artifact_path),
        "task": task,
        "next_skill": "evaluation",
        "next_skill_input": next_skill_input,
    }


def infer_lmms_task_from_samples_path(path_text: str) -> str | None:
    basename = Path(path_text).name
    match = re.search(r"_samples_(.+)\.jsonl$", basename)
    if match:
        return match.group(1)
    parts = Path(path_text).parts
    if len(parts) >= 2:
        return parts[-2]
    return None
