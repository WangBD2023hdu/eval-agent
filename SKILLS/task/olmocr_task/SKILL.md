---
name: olmocr_task
description: Use when an olmOCR Bench job must run LMMS Eval inference, convert the prediction JSONL to Markdown files, run the official olmOCR benchmark, and write a report.
---

# olmOCR Task

This is the entry skill for `olmOCR_bench_250802`. Treat it as the task-level state machine. Do not stop after LMMS Eval inference; inference only produces the JSONL required by the official olmOCR evaluation flow.

## Required Skill Chain

Use these job-referenced skills in order:

1. `inference/lmms-eval-old`
2. `evaluation/olmocr`

Do not run the JSONL-to-Markdown conversion until `scripts/extract_samples.py` returns a real existing `samples_jsonl_abs`.

## Required Inputs

Require:

- `job.checkpoint.path`
- `job.task.name`
- `job.inference.skill=lmms-eval-old`
- `job.evaluation.skill=olmocr`
- `job.outputs.report_path`

If any required value is missing, call `ask_user` with the missing field name.

## Execution Order

Follow this sequence. Dependent steps must happen in separate turns; do not batch GPU-contending inference, conversion, benchmark, and parsing steps together.

1. Start LMMS Eval inference with `start_long_command` using the `lmms-eval-old` skill.
2. Wait for inference with `wait_long_command`.
3. If inference fails, report the real `status`, `returncode`, `signal`, `log_path`, and `log_tail`; do not start olmOCR evaluation.
4. On inference success, use `run_command` to execute `<skill_context.referenced_inference_skill.script_dir>/extract_samples.py` with the inference `log_path`, LMMS Eval cwd, and task name. Parse the JSON stdout.
5. Use the `olmocr` evaluation skill to convert `next_skill_input.prediction_jsonl` to Markdown files with `scripts/infinity_parser2_jsonl2md.py`.
6. Wait for the conversion command. If it fails, report the real failure details; do not start the benchmark.
7. Start the official benchmark with `python -m olmocr.bench.benchmark --dir ./olmOCR-bench/bench_data --candidate <md_result_dir>`.
8. Wait for the benchmark command. If it fails, report the real failure details; do not invent metrics.
9. On benchmark success, use `run_command` to execute `<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py` with the benchmark `log_path`, olmOCR cwd, `job.outputs.report_path`, and `job.outputs.root` as `--workspace`. Parse the JSON stdout.
10. Finish only after `scripts/extract_metrics.py` returns the average score, category scores, per-JSONL scores, and Markdown report path.

## Resume Rules

If state/history shows a long command is still running, use `inspect_long_command` before starting a new command.

If inference already succeeded but the JSONL was not extracted, run `scripts/extract_samples.py` from the recorded inference `log_path`.

If a prediction JSONL already exists in state, skip rerunning inference and continue to JSONL-to-Markdown conversion.

If conversion already succeeded but benchmark was not run, continue with the official olmOCR benchmark using the same `<md_result_dir>`.

If the benchmark already succeeded but metrics were not extracted, run `scripts/extract_metrics.py` from the recorded benchmark `log_path`.

## Completion Criteria

Call `finish` only when all are true:

- LMMS Eval inference command succeeded.
- `scripts/extract_samples.py` returned an existing prediction JSONL.
- JSONL-to-Markdown conversion command succeeded.
- Official olmOCR benchmark command succeeded.
- `scripts/extract_metrics.py` returned `average_score_percent`, `confidence_interval_percent`, category scores, and per-JSONL scores.
- The report Markdown was written under the workspace write root.

The final message must include the prediction JSONL path, md result directory, benchmark log path, Markdown report path, and average score.
