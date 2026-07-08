#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
FLOAT = r"[-+]?\d+(?:\.\d+)?"
SUMMARY_RE = re.compile(
    rf"^\s*(?P<candidate>.+?)\s*:\s*Average Score:\s*"
    rf"(?P<average>{FLOAT})%\s*(?:\u00b1|\+/-|\+-)\s*"
    rf"(?P<ci>{FLOAT})%",
    re.MULTILINE,
)
CATEGORY_NAMES = ("absent", "baseline", "math", "order", "present", "table")
CATEGORY_RE = re.compile(
    rf"^\s*(absent|baseline|math|order|present|table)\s*:\s*"
    rf"({FLOAT})%\s+average pass rate over\s+(\d+)\s+tests\s*$",
    re.MULTILINE,
)
JSONL_RE = re.compile(
    rf"^\s*([^:\n]+?)\s*:\s*({FLOAT})%\s*"
    r"\((\d+)/(\d+)\s+tests\)\s*$",
    re.MULTILINE,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract official olmOCR benchmark metrics from a real log.")
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--candidate")
    parser.add_argument("--markdown-path")
    parser.add_argument("--workspace")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = extract_metrics(
            log_path=Path(args.log_path),
            cwd=Path(args.cwd),
            candidate=args.candidate,
            markdown_path=Path(args.markdown_path) if args.markdown_path else None,
            workspace=Path(args.workspace) if args.workspace else None,
            append=not args.overwrite,
        )
    except Exception as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def extract_metrics(
    *,
    log_path: Path,
    cwd: Path,
    candidate: str | None,
    markdown_path: Path | None,
    workspace: Path | None,
    append: bool,
) -> dict[str, object]:
    if not log_path.is_absolute():
        log_path = cwd / log_path
    if not log_path.exists():
        raise FileNotFoundError(f"log file does not exist: {log_path}")

    clean_text = ANSI_ESCAPE_RE.sub("", log_path.read_text(encoding="utf-8", errors="replace"))
    parsed = _extract_summary(clean_text, candidate=candidate)
    markdown = _metrics_markdown(parsed)

    resolved_markdown_path = None
    if markdown_path is not None:
        if workspace is None:
            raise ValueError("--workspace is required when --markdown-path is provided")
        resolved_markdown_path = _resolve_workspace_path(markdown_path, workspace=workspace)
        _write_markdown(resolved_markdown_path, markdown, append=append)

    parsed["metrics_markdown"] = markdown
    parsed["markdown_path"] = str(resolved_markdown_path) if resolved_markdown_path else None
    return parsed


def _extract_summary(text: str, *, candidate: str | None) -> dict[str, object]:
    if "Final Summary with 95% Confidence Intervals:" not in text:
        raise ValueError("could not find olmOCR final summary block")

    summary_match = SUMMARY_RE.search(text)
    if not summary_match:
        raise ValueError("could not find olmOCR average score line")

    parsed_candidate = summary_match.group("candidate").strip()
    if candidate and candidate != parsed_candidate:
        parsed_candidate = candidate

    category_scores = {
        name: {"score_percent": float(score), "tests": int(tests)}
        for name, score, tests in CATEGORY_RE.findall(text)
    }
    missing_categories = [name for name in CATEGORY_NAMES if name not in category_scores]
    if missing_categories:
        raise ValueError(f"missing olmOCR category score(s): {', '.join(missing_categories)}")

    jsonl_section = text.split("Results by JSONL file:", 1)
    if len(jsonl_section) != 2:
        raise ValueError("could not find olmOCR per-JSONL results block")
    jsonl_scores = {
        name.strip(): {
            "score_percent": float(score),
            "passed": int(passed),
            "total": int(total),
        }
        for name, score, passed, total in JSONL_RE.findall(jsonl_section[1])
    }
    if not jsonl_scores:
        raise ValueError("could not find olmOCR per-JSONL scores")

    return {
        "candidate": parsed_candidate,
        "average_score_percent": float(summary_match.group("average")),
        "confidence_interval_percent": float(summary_match.group("ci")),
        "category_scores": {name: category_scores[name] for name in CATEGORY_NAMES},
        "jsonl_scores": jsonl_scores,
    }


def _metrics_markdown(result: dict[str, object]) -> str:
    category_scores = result["category_scores"]
    jsonl_scores = result["jsonl_scores"]
    assert isinstance(category_scores, dict)
    assert isinstance(jsonl_scores, dict)

    lines = [
        "## olmOCR Bench Metrics",
        "",
        f"Candidate: `{result['candidate']}`",
        "",
        "| Metric | Value |",
        "|---|---:|",
        (
            f"| Average Score | {result['average_score_percent']}% +/- "
            f"{result['confidence_interval_percent']}% |"
        ),
        "",
        "### Category Scores",
        "",
        "| Category | Pass Rate | Tests |",
        "|---|---:|---:|",
    ]
    for name in CATEGORY_NAMES:
        item = category_scores[name]
        assert isinstance(item, dict)
        lines.append(f"| {name} | {item['score_percent']}% | {item['tests']} |")

    lines.extend(
        [
            "",
            "### Results by JSONL File",
            "",
            "| JSONL | Pass Rate | Passed/Total |",
            "|---|---:|---:|",
        ]
    )
    for name, item in jsonl_scores.items():
        assert isinstance(item, dict)
        lines.append(f"| {name} | {item['score_percent']}% | {item['passed']}/{item['total']} |")
    return "\n".join(lines) + "\n"


def _resolve_workspace_path(path: Path, *, workspace: Path) -> Path:
    root = workspace.resolve()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError(f"markdown path outside workspace: {resolved}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _write_markdown(path: Path, markdown: str, *, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append and path.exists():
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + markdown)
    else:
        path.write_text(markdown, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
