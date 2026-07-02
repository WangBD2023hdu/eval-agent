from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .client import OpenAIChatClient
from .config import AgentConfig
from .errors import AgentLoopError
from .long_commands import cancel_active_long_commands
from .progress import stderr_progress
from .runner import run_loop


LOCAL_NO_PROXY_ENTRIES = ("localhost", "127.0.0.1", "127.0.1.1", "0.0.0.0", "::1")


@dataclass(frozen=True)
class RuntimePaths:
    job_path: Path
    state_path: Path | None
    workspace: Path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real OpenAI-compatible evaluation agent loop.")
    parser.add_argument("--job", help="Path to job JSON/YAML. Optional when --checkpoint, --task, and --report-dir are provided.")
    parser.add_argument("--skills-dir", default="SKILLS", help="Directory containing inference/evaluation/task skills")
    parser.add_argument("--state", help="Path to persistent state JSON")
    parser.add_argument("--workspace", help="Workspace and write root for agent-managed files")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:8000/v1")
    parser.add_argument("--api-key", help="API key. Use EMPTY for local vLLM when appropriate.")
    parser.add_argument("--model", "--agent-model", dest="model", default="qwen3-5", help="Agent model name")
    parser.add_argument("--checkpoint", help="Model checkpoint path to evaluate")
    parser.add_argument("--task", help="Evaluation task name")
    parser.add_argument("--report-dir", help="Directory where generated job, state, logs, and report artifacts should live; used as write root when --workspace is omitted")
    parser.add_argument("--run-id", help="Run identifier for generated jobs")
    parser.add_argument("--inference-skill", default="lmms-eval-old", help="Inference skill name for generated jobs")
    parser.add_argument("--evaluation-skill", default="omnidocbench", help="Evaluation skill name for generated jobs")
    parser.add_argument("--worker-cuda-visible-devices", help="CUDA_VISIBLE_DEVICES for skill subprocesses, e.g. 0,1")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
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
    apply_worker_environment(args)

    runtime = prepare_runtime(args)
    config = AgentConfig.from_env(env)
    client = OpenAIChatClient(config)
    result = run_loop(
        client=client,
        config=config,
        skills_dir=Path(args.skills_dir),
        job_path=runtime.job_path,
        state_path=runtime.state_path,
        workspace=runtime.workspace,
        progress=stderr_progress,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


def entrypoint() -> int:
    try:
        return main()
    except KeyboardInterrupt:
        sys.stderr.write("\nagent-loop interrupted; cancelling active long commands...\n")
        for result in cancel_active_long_commands():
            sys.stderr.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return 130
    except AgentLoopError as exc:
        sys.stderr.write(f"agent-loop error: {exc}\n")
        return 2


def apply_worker_environment(args: argparse.Namespace, *, env: dict[str, str] | None = None) -> None:
    target = os.environ if env is None else env
    if args.worker_cuda_visible_devices:
        target["CUDA_VISIBLE_DEVICES"] = args.worker_cuda_visible_devices
    _append_local_no_proxy(target, "NO_PROXY")
    _append_local_no_proxy(target, "no_proxy")


def _append_local_no_proxy(env: dict[str, str], key: str) -> None:
    existing = [item.strip() for item in env.get(key, "").split(",") if item.strip()]
    seen = set(existing)
    for entry in LOCAL_NO_PROXY_ENTRIES:
        if entry not in seen:
            existing.append(entry)
            seen.add(entry)
    env[key] = ",".join(existing)


def prepare_runtime(args: argparse.Namespace) -> RuntimePaths:
    if args.job:
        return RuntimePaths(
            job_path=Path(args.job).resolve(),
            state_path=Path(args.state).resolve() if args.state else None,
            workspace=Path(args.workspace).resolve() if args.workspace else Path(".").resolve(),
        )

    missing = [
        name
        for name in ("checkpoint", "task", "report_dir")
        if not getattr(args, name, None)
    ]
    if missing:
        joined = ", ".join("--" + name.replace("_", "-") for name in missing)
        raise AgentLoopError(f"--job is required unless generated-job fields are provided: {joined}")
    _validate_generated_runtime(args)

    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    job_path = report_dir / "job.json"
    job_path.write_text(
        json.dumps(_build_generated_job(args, report_dir=report_dir), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimePaths(
        job_path=job_path,
        state_path=Path(args.state).resolve() if args.state else report_dir / "agent_state.json",
        workspace=Path(args.workspace).resolve() if args.workspace else report_dir,
    )


def _build_generated_job(args: argparse.Namespace, *, report_dir: Path) -> dict[str, object]:
    run_id = args.run_id or f"{args.task}-{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    return {
        "run_id": run_id,
        "agent": {
            "model": args.model,
            "base_url": args.base_url,
        },
        "checkpoint": {
            "path": args.checkpoint,
        },
        "task": {
            "name": args.task,
        },
        "inference": {
            "skill": args.inference_skill,
            "model_weight": args.checkpoint,
            "task": args.task,
        },
        "evaluation": {
            "skill": args.evaluation_skill,
            "task": args.task,
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


def _validate_generated_runtime(args: argparse.Namespace) -> None:
    if args.inference_skill != "lmms-eval-old" or not args.base_url:
        return

    parsed = urlparse(args.base_url)
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError as exc:
        raise AgentLoopError(f"invalid --base-url: {args.base_url}") from exc
    if hostname in {"127.0.0.1", "localhost", "::1"} and port == 8000:
        raise AgentLoopError(
            "agent --base-url uses local port 8000, but lmms-eval-old also uses "
            "http://localhost:8000/v1 for inference. Start the agent model on a "
            "different port, for example 8001, and pass --base-url http://127.0.0.1:8001/v1."
        )
