from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import AgentLoopError
from .lmms import ANSI_ESCAPE_RE
from .path_policy import resolve_write_path


EXPECTED_METRICS = (
    "text_block_Edit_dist",
    "display_formula_CDM",
    "table_TEDS",
    "table_TEDS_structure_only",
    "reading_order_Edit_dist",
    "overall_notebook",
)
RUN_REPORT_RE = re.compile(r"END_FINAL_EVAL_RUN_REPORT\s+([^\s=]+)")
SAVED_FILE_RE = re.compile(r"^\[([^\]]+)\]\s+saved to\s+(.+?)\s*$", re.MULTILINE)
METRIC_RE = re.compile(r"^\s*([A-Za-z0-9_]+):\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$", re.MULTILINE)


def extract_omnidocbench_metrics(action: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    cwd = Path(action.get("cwd") or workspace)
    text = _read_text(action, cwd=cwd)
    clean_text = ANSI_ESCAPE_RE.sub("", text)
    run_id = _extract_run_id(clean_text)
    metrics = _extract_metrics(clean_text)
    report_files, report_files_abs = _extract_report_files(clean_text, cwd=cwd)
    markdown = _metrics_markdown(run_id=run_id, metrics=metrics, report_files=report_files_abs)

    markdown_path = action.get("markdown_path")
    if isinstance(markdown_path, str) and markdown_path:
        resolved_markdown_path = resolve_write_path(
            markdown_path,
            workspace=workspace,
            field="extract_omnidocbench_metrics.markdown_path",
        )
        _write_markdown(resolved_markdown_path, markdown, append=bool(action.get("append", True)))
    else:
        resolved_markdown_path = None

    return {
        "action": "extract_omnidocbench_metrics",
        "run_id": run_id,
        "metrics": metrics,
        "metrics_markdown": markdown,
        "report_files": report_files,
        "report_files_abs": report_files_abs,
        "markdown_path": str(resolved_markdown_path) if resolved_markdown_path else None,
    }


def _read_text(action: dict[str, Any], *, cwd: Path) -> str:
    parts: list[str] = []
    if isinstance(action.get("text"), str):
        parts.append(action["text"])
    if isinstance(action.get("log_path"), str):
        log_path = Path(action["log_path"])
        if not log_path.is_absolute():
            log_path = cwd / log_path
        parts.append(log_path.read_text(encoding="utf-8", errors="replace"))
    if not parts:
        raise AgentLoopError("extract_omnidocbench_metrics requires text or log_path")
    return "\n".join(parts)


def _extract_run_id(text: str) -> str | None:
    match = RUN_REPORT_RE.search(text)
    return match.group(1) if match else None


def _extract_metrics(text: str) -> dict[str, float]:
    if "[notebook_metric_summary]" not in text:
        raise AgentLoopError("could not find [notebook_metric_summary] in OmniDocBench output")
    after_marker = text.split("[notebook_metric_summary]", 1)[1]
    block = after_marker.split("\n[", 1)[0]
    metrics = {name: float(value) for name, value in METRIC_RE.findall(block)}
    missing = [name for name in EXPECTED_METRICS if name not in metrics]
    if missing:
        raise AgentLoopError(f"missing OmniDocBench metric(s): {', '.join(missing)}")
    return {name: metrics[name] for name in EXPECTED_METRICS}


def _extract_report_files(text: str, *, cwd: Path) -> tuple[dict[str, str], dict[str, str]]:
    report_files: dict[str, str] = {}
    report_files_abs: dict[str, str] = {}
    for key, raw_path in SAVED_FILE_RE.findall(text):
        path_text = raw_path.strip()
        report_files[key] = path_text
        path = Path(path_text)
        if not path.is_absolute():
            path = cwd / path
        report_files_abs[key] = str(path.resolve())
    return report_files, report_files_abs


def _metrics_markdown(*, run_id: str | None, metrics: dict[str, float], report_files: dict[str, str]) -> str:
    lines = ["## OmniDocBench Metrics", ""]
    if run_id:
        lines.extend([f"Run ID: `{run_id}`", ""])
    lines.extend(["| Metric | Value |", "|---|---:|"])
    for name in EXPECTED_METRICS:
        lines.append(f"| {name} | {metrics[name]} |")
    if report_files:
        lines.extend(["", "### OmniDocBench Artifacts", ""])
        for key, path in report_files.items():
            lines.append(f"- `{key}`: `{path}`")
    return "\n".join(lines) + "\n"


def _write_markdown(path: Path, markdown: str, *, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append and path.exists():
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + markdown)
    else:
        path.write_text(markdown, encoding="utf-8")
