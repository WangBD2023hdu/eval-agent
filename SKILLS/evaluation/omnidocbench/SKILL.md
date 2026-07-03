---
name: omnidocbench
description: Use when running the real OmniDocBench evaluation script on an LMMS Eval prediction JSONL and extracting notebook metrics for a Markdown report.
---

# OmniDocBench

Run the real OmniDocBench benchmark. Do not simulate scores, report files, metric summaries, or success states.

## Inputs

Require:

- `prediction_jsonl`: absolute path to the LMMS Eval per-sample JSONL file.

Optional:

- `report_path`: Markdown file that should receive the OmniDocBench metric table. Prefer `job.outputs.report_path` when present.

Example prediction path:

```text
/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old/logs/qwen3_5_vllm/omnidocbench_v1_6/20260702_140820_samples_omnidocbench_v1_6.jsonl
```

## Working Directory

Always run from:

```text
/home/ma-user/work/wangbaode/07_evaluate/OmniDocBench
```

Before running, use real commands to verify:

- the working directory exists
- `pdf_validation.py` exists
- `prediction_jsonl` exists

If any required path is missing, return `ask_user` with the missing path.

## Command

Use `start_long_command` for the benchmark run:

```json
{
  "action": "start_long_command",
  "cwd": "/home/ma-user/work/wangbaode/07_evaluate/OmniDocBench",
  "skill_type": "evaluation",
  "label": "omnidocbench",
  "argv": [
    "python",
    "pdf_validation.py",
    "--input_file=<prediction_jsonl>"
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

If the command exits non-zero, is killed, or times out, report the real `status`, `returncode`, `signal`, `log_path`, and `log_tail`. Do not parse or invent scores from an incomplete failed run unless the user explicitly asks to inspect partial artifacts.

## Metric Extraction

On successful completion, parse metrics from the real benchmark output using this skill's own script with the generic `run_command` tool. The script path is:

```text
<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py
```

Call it with the benchmark log path:

```json
{
  "action": "run_command",
  "cwd": "/home/ma-user/work/wangbaode/07_evaluate/OmniDocBench",
  "argv": [
    "python3",
    "<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py",
    "--log-path",
    "<log_path from wait_long_command>",
    "--cwd",
    "/home/ma-user/work/wangbaode/07_evaluate/OmniDocBench",
    "--markdown-path",
    "<report_path>",
    "--workspace",
    "<job.outputs.root>"
  ]
}
```

The script prints JSON to stdout and writes the Markdown report under the workspace. It extracts this required metric set:

```text
text_block_Edit_dist
display_formula_CDM
table_TEDS
table_TEDS_structure_only
reading_order_Edit_dist
overall_notebook
```

It also extracts benchmark artifact paths printed as:

```text
[final-eval-run-report] saved to ./result/<run>_run_summary.json
[runtime-environment-json] saved to ./result/<run>_runtime_environment.json
[runtime-environment-log] saved to ./result/<run>_runtime_environment.log
[stage-execution-json] saved to ./result/<run>_stage_execution.json
[stage-execution-log] saved to ./result/<run>_stage_execution.log
```

## Output Contract

Evaluation is complete only when all are true:

- `wait_long_command.status` is `succeeded`
- `wait_long_command.returncode` is `0`
- `scripts/extract_metrics.py` returns all six required metrics
- the Markdown report contains the OmniDocBench metric table

Return the structured metrics and Markdown report path to the task skill. Include `overall_notebook` in the final summary.

If the interactive session cannot wait for completion, preserve `command_id`, `metadata_path`, `log_path`, `prediction_jsonl`, and `report_path`. A later loop must use `inspect_long_command` before continuing.
