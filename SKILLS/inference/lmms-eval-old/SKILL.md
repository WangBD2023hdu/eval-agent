---
name: lmms-eval-old
description: Run the real legacy LMMS Eval script at /home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old for Qwen3.5/vLLM inference. Use when the task asks to run lmms-eval-old with a model weight path and task name, especially the default model weight under the DocVEP checkpoint and task omnidocbench_v1_6.
---

# LMMS Eval Old

Run the real legacy LMMS Eval command. Do not simulate model output, prediction JSONL, logs, process status, or benchmark results.

## Parameters

Require exactly these two user/task parameters:

- `model_weight`: path to the HuggingFace model weights.
- `task`: LMMS Eval task name.

Default values for the current evaluation:

```text
model_weight=/inspire/sfs/project/inf-multimodal/public/wangbaode/01_gitlab/verl/checkpoints/DocVEP/infinity_parser3_doc2md_random_text_privileged_megatron/global_step_300/actor/model/huggingface
task=omnidocbench_v1_6
```

The prompt template and tensor parallel size are fixed for this skill unless the user explicitly changes them:

```text
tensor_parallel_size=2
prompt=lmms_eval/prompts/prompt_infinity_parser2_doc2md.jinja
```

Default batch size for this skill is 4. Keep it explicit as the third script argument because OmniDocBench PDF/image requests can overload the local vLLM server at the script default of 32. Only increase it when the user explicitly asks.

## Working Directory

Always run from:

```text
/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old
```

Before running, use a real command to verify the directory and script exist. If either is missing, return `ask_user` with the missing path.

## Command

Use the agent loop `start_long_command` action with `cwd` set to the working directory and `argv` set exactly in this shape:

```json
{
  "action": "start_long_command",
  "cwd": "/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old",
  "skill_type": "inference",
  "label": "lmms-eval-old omnidocbench_v1_6",
  "argv": [
    "bash",
    "scripts/evaluate_qwen3_5_vllm_agent.sh",
    "model_version=<model_weight>,tensor_parallel_size=2,prompt=lmms_eval/prompts/prompt_infinity_parser2_doc2md.jinja",
    "<task>",
    "4"
  ]
}
```

For the default values, the effective command is:

```bash
bash scripts/evaluate_qwen3_5_vllm_agent.sh "model_version=/inspire/sfs/project/inf-multimodal/public/wangbaode/01_gitlab/verl/checkpoints/DocVEP/infinity_parser3_doc2md_random_text_privileged_megatron/global_step_300/actor/model/huggingface,tensor_parallel_size=2,prompt=lmms_eval/prompts/prompt_infinity_parser2_doc2md.jinja" "omnidocbench_v1_6" "4"
```

## Completion Rules

After starting the command, use `wait_long_command` with the returned `command_id`:

```json
{
  "action": "wait_long_command",
  "command_id": "<command_id>",
  "timeout_sec": 86400
}
```

Treat the run as successful only when the long command returns `status=succeeded`, `returncode=0`, and the script's real output/logs identify the produced artifact path. If the command fails, report the real status, exit code, signal, log path, and log tail. Do not invent output paths.

After the command exits, extract the per-sample JSONL path from the real stdout/stderr or log file. The legacy script writes a line like:

```text
Results saved in logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl
```

Use the `extract_lmms_eval_samples` tool with the command output or log path:

```json
{
  "action": "extract_lmms_eval_samples",
  "log_path": "<log_path from wait_long_command>",
  "cwd": "/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old",
  "task": "<task>",
  "require_exists": true
}
```

This tool returns:

```json
{
  "samples_jsonl": "logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl",
  "samples_jsonl_abs": "/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old/logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl",
  "next_skill": "evaluation",
  "next_skill_input": {
    "prediction_jsonl": "/home/ma-user/work/wangbaode/07_evaluate/lmms-eval-old/logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl",
    "task": "omnidocbench_v1_6"
  }
}
```

Pass `next_skill_input.prediction_jsonl` to the downstream evaluation skill. Do not proceed to evaluation if `extract_lmms_eval_samples` cannot find the path or the JSONL file does not exist.

If the command runs longer than the interactive session can wait, preserve the returned `command_id`, `metadata_path`, `log_path`, cwd, task, and model weight. A later loop must use `inspect_long_command` before deciding whether to continue waiting, extract artifacts, or report failure.
