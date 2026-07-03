---
name: omnidocbench_task
description: Use when an OmniDocBench job must run LMMS Eval inference before running OmniDocBench evaluation and writing a report.
---

# OmniDocBench Task

This is the entry skill for `omnidocbench_v1_6`. Treat it as the task-level state machine. Do not stop after inference; inference only produces the prediction JSONL required by OmniDocBench.

## Required Skill Chain

Use these job-referenced skills in order:

1. `inference/lmms-eval-old`
2. `evaluation/omnidocbench`

Do not run the evaluation before `scripts/extract_samples.py` returns a real existing `samples_jsonl_abs`.

## Required Inputs

Require:

- `job.checkpoint.path`
- `job.task.name`
- `job.inference.skill=lmms-eval-old`
- `job.evaluation.skill=omnidocbench`
- `job.outputs.report_path`

If any required value is missing, call `ask_user` with the missing field name.

## Execution Order

Follow this sequence. Dependent steps must happen in separate turns; do not batch GPU-contending commands with their downstream parse/evaluation steps.

1. Start LMMS Eval inference with `start_long_command` using the `lmms-eval-old` skill.
2. Wait for inference with `wait_long_command`.
3. If inference fails, report the real `status`, `returncode`, `signal`, `log_path`, and `log_tail`; do not start OmniDocBench.
4. On inference success, use `run_command` to execute `<skill_context.referenced_inference_skill.script_dir>/extract_samples.py` with the inference `log_path`, LMMS Eval cwd, and task name. Parse the JSON stdout.
5. Start OmniDocBench evaluation with `start_long_command`, passing `next_skill_input.prediction_jsonl` from the `scripts/extract_samples.py` JSON stdout.
6. Wait for OmniDocBench with `wait_long_command`.
7. If evaluation fails, report the real failure details; do not invent metrics.
8. On evaluation success, use `run_command` to execute `<skill_context.referenced_evaluation_skill.script_dir>/extract_metrics.py` with the evaluation `log_path`, OmniDocBench cwd, `job.outputs.report_path`, and `job.outputs.root` as `--workspace`. Parse the JSON stdout.
9. Finish only after `scripts/extract_metrics.py` returns all required metrics and the Markdown report path.

## Resume Rules

If state/history shows a long command is still running, use `inspect_long_command` before starting a new command.

If inference already succeeded but the JSONL was not extracted, run `scripts/extract_samples.py` from the recorded inference `log_path`.

If a prediction JSONL already exists in state, skip rerunning inference and continue to OmniDocBench evaluation.

If OmniDocBench already succeeded but metrics were not extracted, run `scripts/extract_metrics.py` from the recorded evaluation `log_path`.

## Completion Criteria

Call `finish` only when all are true:

- LMMS Eval inference command succeeded.
- `scripts/extract_samples.py` returned an existing prediction JSONL.
- OmniDocBench evaluation command succeeded.
- `scripts/extract_metrics.py` returned `text_block_Edit_dist`, `display_formula_CDM`, `table_TEDS`, `table_TEDS_structure_only`, `reading_order_Edit_dist`, and `overall_notebook`.
- The report Markdown was written under the workspace write root.

The final message must include the prediction JSONL path, OmniDocBench log path, Markdown report path, and `overall_notebook`.
