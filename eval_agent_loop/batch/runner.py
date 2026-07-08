from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..core.config import AgentConfig
from ..core.errors import AgentLoopError
from ..core.progress import stderr_progress
from ..loop.runner import run_loop
from ..loop.skills import (
    default_evaluation_skill_name,
    default_inference_skill_name,
    default_task_skill_name,
)


RunOneJob = Callable[..., dict[str, Any]]


def run_batch(args: argparse.Namespace, *, run_one_job: RunOneJob | None = None) -> dict[str, Any]:
    if not args.batch_jsonl:
        raise AgentLoopError("--batch-jsonl is required for batch execution")
    if not args.report_dir:
        raise AgentLoopError("--report-dir is required for batch execution")

    report_root = Path(args.report_dir).resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    items = list(_iter_batch_jobs(args, report_root=report_root))
    summary_path = report_root / "batch_summary.jsonl"
    markdown_path = report_root / "batch_summary.md"
    summary_path.write_text("", encoding="utf-8")
    runner = run_one_job or (lambda *, job_path, state_path, workspace: _run_one_job(args, job_path=job_path, state_path=state_path, workspace=workspace))

    records: list[dict[str, Any]] = []
    for index, job_path, state_path, workspace in items:
        started_at = _utc_now()
        try:
            result = runner(job_path=job_path, state_path=state_path, workspace=workspace)
            status = "succeeded" if result.get("action") == "finish" else "failed"
            record = {
                "index": index,
                "status": status,
                "job_path": str(job_path),
                "state_path": str(state_path),
                "workspace": str(workspace),
                "report_path": str(workspace / "report.md"),
                "started_at": started_at,
                "ended_at": _utc_now(),
                "result": result,
            }
        except Exception as exc:
            record = {
                "index": index,
                "status": "failed",
                "job_path": str(job_path),
                "state_path": str(state_path),
                "workspace": str(workspace),
                "report_path": str(workspace / "report.md"),
                "started_at": started_at,
                "ended_at": _utc_now(),
                "error": str(exc),
            }
        records.append(record)
        _append_jsonl(summary_path, record)
        _write_markdown_summary(markdown_path, records)

    succeeded = sum(1 for record in records if record["status"] == "succeeded")
    failed = len(records) - succeeded
    return {
        "action": "batch_finish",
        "total": len(records),
        "succeeded": succeeded,
        "failed": failed,
        "summary_path": str(summary_path),
        "markdown_path": str(markdown_path),
    }


def _run_one_job(args: argparse.Namespace, *, job_path: Path, state_path: Path, workspace: Path) -> dict[str, Any]:
    from ..core.client import OpenAIChatClient

    config = AgentConfig.from_env(_agent_env(args))
    client = OpenAIChatClient(config)
    return run_loop(
        client=client,
        config=config,
        skills_dir=Path(args.skills_dir),
        job_path=job_path,
        state_path=state_path,
        workspace=workspace,
        progress=stderr_progress,
    )


def _agent_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    if args.base_url:
        env["AGENT_BASE_URL"] = args.base_url
    if args.api_key:
        env["AGENT_API_KEY"] = args.api_key
    if args.model:
        env["AGENT_MODEL"] = args.model
    if args.max_iterations is not None:
        env["AGENT_MAX_ITERATIONS"] = str(args.max_iterations)
    if args.temperature is not None:
        env["AGENT_TEMPERATURE"] = str(args.temperature)
    return env


def _iter_batch_jobs(args: argparse.Namespace, *, report_root: Path) -> list[tuple[int, Path, Path, Path]]:
    jobs: list[tuple[int, Path, Path, Path]] = []
    index = 0
    for entry in _read_manifest(Path(args.batch_jsonl)):
        checkpoint = entry["ckp"]
        for task_name in entry["task"]:
            index += 1
            workspace = report_root / _job_dir_name(index=index, checkpoint=checkpoint, task=task_name)
            workspace.mkdir(parents=True, exist_ok=True)
            job_path = workspace / "job.json"
            state_path = workspace / "agent_state.json"
            job_path.write_text(
                json.dumps(
                    _build_job(args, checkpoint=checkpoint, task_name=task_name, report_dir=workspace),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            jobs.append((index, job_path, state_path, workspace))
    return jobs


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AgentLoopError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise AgentLoopError(f"batch entry must be an object at {path}:{line_number}")
        checkpoint = entry.get("ckp")
        tasks = entry.get("task")
        if not isinstance(checkpoint, str) or not checkpoint:
            raise AgentLoopError(f"batch entry requires non-empty string field 'ckp' at {path}:{line_number}")
        if not isinstance(tasks, list) or not tasks or not all(isinstance(task, str) and task for task in tasks):
            raise AgentLoopError(f"batch entry requires non-empty string list field 'task' at {path}:{line_number}")
        entries.append({"ckp": checkpoint, "task": tasks})
    if not entries:
        raise AgentLoopError(f"batch manifest is empty: {path}")
    return entries


def _build_job(args: argparse.Namespace, *, checkpoint: str, task_name: str, report_dir: Path) -> dict[str, Any]:
    run_id = f"{task_name}-{_slug(Path(checkpoint).name)}-{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    task_skill = args.task_skill or default_task_skill_name(task_name)
    inference_skill = args.inference_skill or default_inference_skill_name(task_name)
    evaluation_skill = args.evaluation_skill or default_evaluation_skill_name(task_name)
    return {
        "run_id": run_id,
        "agent": {
            "model": args.model,
            "base_url": args.base_url,
        },
        "checkpoint": {
            "path": checkpoint,
        },
        "task": {
            "name": task_name,
            "skill": task_skill,
        },
        "inference": {
            "skill": inference_skill,
            "model_weight": checkpoint,
            "task": task_name,
        },
        "evaluation": {
            "skill": evaluation_skill,
            "task": task_name,
        },
        "runtime": {
            "worker_cuda_visible_devices": args.worker_cuda_visible_devices,
        },
        "outputs": {
            "root": str(report_dir),
            "report_dir": str(report_dir),
            "report_path": str(report_dir / "report.md"),
        },
    }


def _job_dir_name(*, index: int, checkpoint: str, task: str) -> str:
    return f"{index:04d}_{_slug(task)}_{_slug(Path(checkpoint).name)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return slug.strip("-") or "item"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_markdown_summary(path: Path, records: list[dict[str, Any]]) -> None:
    lines = ["# Batch Evaluation Summary", "", "| # | Status | Job | Report |", "|---:|---|---|---|"]
    for record in records:
        lines.append(
            f"| {record['index']} | {record['status']} | `{record['job_path']}` | `{record['report_path']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
