---
name: olmocr
description: Use when running the official olmOCR benchmark on Markdown files converted from an LMMS Eval prediction JSONL and extracting score summaries for a Markdown report.
---

# olmOCR Evaluation

Run the real official olmOCR evaluation flow. Do not simulate scores, Markdown outputs, pass counts, report files, or success states.

## Inputs

Require:

- `prediction_jsonl`: absolute path to the LMMS Eval per-sample JSONL file.

Optional:

- `md_result_dir`: candidate directory name under `./olmOCR-bench/bench_data`. Prefer a sanitized `job.run_id`; otherwise derive it from the prediction JSONL stem.
- `report_path`: Markdown file that should receive the olmOCR metric summary. Prefer `job.outputs.report_path` when present.

## Working Directory

Always run from:

```text
/inspire/sfs/project/inf-multimodal/public/wangbaode/07_evaluate/olmocr
```

Before running, use real commands to verify:

- the working directory exists
- `scripts/infinity_parser2_jsonl2md.py` exists
- `olmOCR-bench/bench_data` exists
- `prediction_jsonl` exists

If any required path is missing, return `ask_user` with the missing path.

## JSONL to Markdown Conversion

Choose `<md_result_dir>` as a path-safe directory name with no slashes. Use `start_long_command` for the conversion:

```json
{
  "action": "start_long_command",
  "cwd": "/inspire/sfs/project/inf-multimodal/public/wangbaode/07_evaluate/olmocr",
  "skill_type": "evaluation",
  "label": "olmocr jsonl2md <md_result_dir>",
  "argv": [
    "python",
    "scripts/infinity_parser2_jsonl2md.py",
    "<prediction_jsonl>",
    "./olmOCR-bench/bench_data/<md_result_dir>"
  ]
}
```

Then wait for completion:

```json
{
  "action": "wait_long_command",
  "command_id": "<command_id>",
  "timeout_sec": 86400
}
```

If conversion exits non-zero, is killed, or times out, report the real `status`, `returncode`, `signal`, `log_path`, and `log_tail`. Do not run the benchmark.

## Benchmark Command

After conversion succeeds, run the official benchmark with `start_long_command`:

```json
{
  "action": "start_long_command",
  "cwd": "/inspire/sfs/project/inf-multimodal/public/wangbaode/07_evaluate/olmocr",
  "skill_type": "evaluation",
  "label": "olmocr benchmark <md_result_dir>",
  "argv": [
    "python",
    "-m",
    "olmocr.bench.benchmark",
    "--dir",
    "./olmOCR-bench/bench_data",
    "--candidate",
    "<md_result_dir>"
  ]
}
```

Then wait for completion:

```json
{
  "action": "wait_long_command",
  "command_id": "<command_id>",
  "timeout_sec": 86400
}
```

If the benchmark exits non-zero, is killed, or times out, report the real `status`, `returncode`, `signal`, `log_path`, and `log_tail`. Do not invent scores from partial logs unless the user explicitly asks to inspect partial artifacts.

## Metric Extraction

On successful benchmark completion, parse metrics from the real benchmark output using this skill's own script with the generic `run_command` tool. The script path is:

```text
<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py
```

Call it with the benchmark log path:

```json
{
  "action": "run_command",
  "cwd": "/inspire/sfs/project/inf-multimodal/public/wangbaode/07_evaluate/olmocr",
  "argv": [
    "python3",
    "<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py",
    "--log-path",
    "<benchmark log_path from wait_long_command>",
    "--cwd",
    "/inspire/sfs/project/inf-multimodal/public/wangbaode/07_evaluate/olmocr",
    "--candidate",
    "<md_result_dir>",
    "--markdown-path",
    "<report_path>",
    "--workspace",
    "<job.outputs.root>"
  ]
}
```

The script prints JSON to stdout and writes the Markdown report under the workspace. It extracts:

- average score and confidence interval
- category pass rates for `absent`, `baseline`, `math`, `order`, `present`, and `table`
- per-JSONL pass rates and passed/total counts

The expected benchmark log contains a summary like:

```text
Final Summary with 95% Confidence Intervals:
<md_result_dir> : Average Score: 86.7% +/- 0.8% (average of per-JSONL scores)
    absent   : 93.7% average pass rate over 823 tests
    baseline : 99.7% average pass rate over 1403 tests
    math     : 88.6% average pass rate over 3385 tests
    order    : 76.3% average pass rate over 1061 tests
    present  : 78.4% average pass rate over 721 tests
    table    : 89.4% average pass rate over 1020 tests

    Results by JSONL file:
        arxiv_math.jsonl : 88.3% (2584/2927 tests)
```

## Output Contract

Evaluation is complete only when all are true:

- JSONL-to-Markdown conversion returned `status=succeeded` and `returncode=0`.
- Official benchmark returned `status=succeeded` and `returncode=0`.
- `scripts/extract_metrics.py` returned `average_score_percent`, `confidence_interval_percent`, category scores, and per-JSONL scores.
- the Markdown report contains the olmOCR metric summary.

Return the structured metrics and Markdown report path to the task skill. Include `average_score_percent` in the final summary.

If the interactive session cannot wait for completion, preserve `command_id`, `metadata_path`, `log_path`, `prediction_jsonl`, `md_result_dir`, and `report_path`. A later loop must use `inspect_long_command` before continuing.
