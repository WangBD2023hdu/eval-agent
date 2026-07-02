---
name: inference
description: Real inference execution instructions for evaluation jobs. Use when an agent must run model inference through actual commands, services, vLLM endpoints, LMMS Eval, or benchmark-owned inference scripts without simulating outputs.
---

# Inference

Run only real inference. Do not fabricate predictions, JSONL rows, model responses, logs, PIDs, endpoints, or success states.

## Inputs

Expect task context to provide:

- model path or model endpoint
- inference mode, such as `lmms_eval`, `vllm_endpoint`, or benchmark-native inference
- GPU allocation
- output directory
- expected prediction artifact path

If any required value is missing, return `ask_user`.

## Procedure

1. Verify the model path or endpoint exists.
2. Verify required commands are installed by running real checks.
3. Create real output directories.
4. Use `run_command` only for short prerequisite checks.
5. Use `start_long_command` for long-running inference, model serving, LMMS Eval, or benchmark-owned inference commands.
6. Use `wait_long_command` to wait for completion when the same agent process owns the command.
7. Use `inspect_long_command` to recover persisted status and log tails for an existing command.
8. Read real logs or output files to confirm completion.
9. Record the exact command, exit code, log path, and artifact path.

## Output Contract

Inference is complete only when a real artifact exists, such as:

- prediction JSONL
- benchmark-native raw output
- reachable vLLM endpoint with `/v1/models`

For long commands, completion requires `status=succeeded`, `returncode=0`, and the expected artifact or endpoint verification. If the command exits non-zero, is killed, times out, or the artifact is missing, do not mark inference complete.
