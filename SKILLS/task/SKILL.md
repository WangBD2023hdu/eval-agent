---
name: task
description: Task orchestration instructions for real evaluation jobs. Use when an agent must decide next steps, maintain state, ask for missing configuration, run inference before evaluation, and finish only after real artifacts are observed.
---

# Task

Coordinate the job as a real state machine. Do not rely on memory alone and do not treat planned work as completed work.

## State Rules

- Use persistent state when provided.
- Record every action and result.
- Treat non-zero command exits as failures.
- Treat long-command `status=failed`, timeout, or missing metadata as incomplete or failed work.
- Treat missing artifacts as incomplete work.
- Ask the user before changing datasets, metrics, model quality settings, dependencies, or destructive filesystem state.

## Action Choice

Prefer this order:

1. Read missing task files or state.
2. Verify prerequisites.
3. Run inference.
4. Run evaluation.
5. Collect reports from real artifacts.
6. Finish with a concise summary.

Use `ask_user` when required information is absent or a recovery would change the meaning of the evaluation.
Use `start_long_command`, `wait_long_command`, and `inspect_long_command` for any long-running inference or evaluation step, not only LMMS Eval.

## Completion Criteria

Return `finish` only when the state references real output artifacts or when the job has reached a clearly reported terminal failure. Include paths to real logs and reports in the message.
