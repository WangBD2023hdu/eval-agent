---
name: evaluation
description: Real benchmark and metric execution instructions for evaluation jobs. Use when an agent must run benchmark scripts, score prediction files, call benchmark-owned inference, parse real metrics, and produce evaluation artifacts without simulating scores.
---

# Evaluation

Run only real benchmark code. Do not invent scores, pass counts, failure counts, leaderboard rows, CSV content, or report files.

## Inputs

Expect task context to provide:

- benchmark name and working directory
- benchmark command or documented entry point
- input type: prediction file or live endpoint
- expected metric artifact paths
- output directory

If a benchmark adapter is incomplete, return `ask_user` with the missing field.

## Procedure

1. Verify benchmark working directory and command.
2. Verify inference inputs exist or endpoint is reachable.
3. Use `run_command` only for short prerequisite checks.
4. Use `start_long_command` for long-running benchmark scoring, benchmark-owned inference, or report generation.
5. Use `wait_long_command` to wait for completion when the same agent process owns the command.
6. Use `inspect_long_command` to recover persisted status and log tails for an existing command.
7. Inspect real output artifacts with `read_file`.
8. Parse metrics only from benchmark-produced files.
9. Preserve raw reports and logs.

## Output Contract

Evaluation is complete only when benchmark-produced metrics or reports exist. If metric parsing fails, report the raw artifact path and error instead of inventing normalized metrics.

For long commands, evaluation is complete only when the command returns `status=succeeded`, `returncode=0`, and benchmark-produced metric/report artifacts exist. If the command exits non-zero, is killed, times out, or produces no metric artifact, report the real status, return code, log path, and log tail.
