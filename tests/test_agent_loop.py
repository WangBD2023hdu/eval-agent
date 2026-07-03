import copy
import json
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import agent_loop
from eval_agent_loop import cli as agent_cli


class ToolCall:
    def __init__(self, tool_id, name, arguments):
        self.id = tool_id
        self.type = "function"
        self.function = type("Function", (), {"name": name, "arguments": json.dumps(arguments)})()


class ScriptedToolClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self.responses:
            raise AssertionError("unexpected extra model call")
        return self.responses.pop(0)


class AgentLoopContractTests(unittest.TestCase):
    def test_agent_loop_is_thin_facade_over_package_modules(self):
        for module_name in (
            "eval_agent_loop.actions",
            "eval_agent_loop.client",
            "eval_agent_loop.command_tools",
            "eval_agent_loop.config",
            "eval_agent_loop.file_tools",
            "eval_agent_loop.long_command_supervisor",
            "eval_agent_loop.long_commands",
            "eval_agent_loop.lmms",
            "eval_agent_loop.messages",
            "eval_agent_loop.omnidocbench",
            "eval_agent_loop.path_policy",
            "eval_agent_loop.progress",
            "eval_agent_loop.runner",
            "eval_agent_loop.skills",
            "eval_agent_loop.state",
            "eval_agent_loop.tool_execution",
            "eval_agent_loop.tool_defs",
        ):
            importlib.import_module(module_name)

        source_lines = Path("agent_loop.py").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(source_lines), 80)

    def test_parse_model_action_accepts_plain_json(self):
        action = agent_loop.parse_model_action('{"action":"finish","message":"done"}')
        self.assertEqual(action["action"], "finish")
        self.assertEqual(action["message"], "done")

    def test_parse_model_action_accepts_json_fence(self):
        action = agent_loop.parse_model_action(
            '```json\n{"action":"ask_user","message":"need config"}\n```'
        )
        self.assertEqual(action["action"], "ask_user")

    def test_validate_action_rejects_simulation(self):
        with self.assertRaises(agent_loop.AgentLoopError):
            agent_loop.validate_action({"action": "simulate", "message": "fake result"})

    def test_validate_run_command_requires_argv_list(self):
        with self.assertRaises(agent_loop.AgentLoopError):
            agent_loop.validate_action({"action": "run_command", "cmd": "echo unsafe"})

    def test_agent_config_requires_real_base_url(self):
        env = {"AGENT_MODEL": "qwen3-5", "AGENT_API_KEY": "EMPTY"}
        with self.assertRaises(agent_loop.AgentLoopError):
            agent_loop.AgentConfig.from_env(env)

    def test_load_skill_bundle_requires_three_skill_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nreal instructions\n", encoding="utf-8")

            bundle = agent_loop.load_skill_bundle(root)

        self.assertEqual(set(bundle), {"inference", "evaluation", "task"})
        self.assertIn("real instructions", bundle["inference"])

    def test_load_skill_bundle_includes_nested_category_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nreal instructions\n", encoding="utf-8")
            nested = root / "inference" / "lmms-eval-old"
            nested.mkdir()
            (nested / "SKILL.md").write_text("# lmms-eval-old\nrun old lmms eval\n", encoding="utf-8")

            bundle = agent_loop.load_skill_bundle(root)

        self.assertIn("inference/lmms-eval-old", bundle)
        self.assertIn("run old lmms eval", bundle["inference/lmms-eval-old"])

    def test_select_skill_context_keeps_only_task_chain_skill_docs(self):
        skills = {
            "inference": "# inference\nrun real inference",
            "inference/lmms-eval-old": "# lmms-eval-old\nrun selected inference",
            "inference/unused": "# unused inference\nSHOULD_NOT_BE_IN_PROMPT",
            "evaluation": "# evaluation\nrun real scoring",
            "evaluation/omnidocbench": "# omnidocbench\nrun selected evaluation",
            "evaluation/unused": "# unused evaluation\nSHOULD_NOT_BE_IN_PROMPT",
            "task": "# task\nmanage jobs",
            "task/omnidocbench_task": "# omnidocbench task\nfirst infer then evaluate",
            "task/unused": "# unused task\nSHOULD_NOT_BE_IN_PROMPT",
        }
        job = {
            "run_id": "job-1",
            "task": {"name": "omnidocbench_v1_6", "skill": "omnidocbench_task"},
            "inference": {"skill": "lmms-eval-old"},
            "evaluation": {"skill": "omnidocbench"},
        }
        state = {"status": "running"}

        skill_context = agent_loop.select_skill_context(skills, job)
        messages = agent_loop.build_messages(skill_context=skill_context, job=job, state=state, events=[])
        joined = "\n".join(message["content"] for message in messages)
        payload = json.loads(messages[1]["content"])

        self.assertEqual(payload["skill_context"]["active_task_skill"]["name"], "task/omnidocbench_task")
        self.assertEqual(payload["skill_context"]["referenced_inference_skill"]["name"], "inference/lmms-eval-old")
        self.assertEqual(payload["skill_context"]["referenced_evaluation_skill"]["name"], "evaluation/omnidocbench")
        self.assertIn("first infer then evaluate", joined)
        self.assertIn("run selected inference", joined)
        self.assertIn("run selected evaluation", joined)
        self.assertNotIn("SHOULD_NOT_BE_IN_PROMPT", joined)
        self.assertIn('"run_id": "job-1"', joined)
        self.assertIn('"status": "running"', joined)
        self.assertIn("Do not simulate", joined)
        self.assertIn("workspace write root", joined)

    def test_load_skill_context_reads_only_job_referenced_nested_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nbase contract\n", encoding="utf-8")
            for category, active, unused in (
                ("task", "omnidocbench_task", "unused_task"),
                ("inference", "lmms-eval-old", "unused_inference"),
                ("evaluation", "omnidocbench", "unused_evaluation"),
            ):
                active_dir = root / category / active
                active_dir.mkdir()
                (active_dir / "SKILL.md").write_text(f"# {active}\nACTIVE_SKILL_CONTENT\n", encoding="utf-8")
                unused_dir = root / category / unused
                unused_dir.mkdir()
                (unused_dir / "SKILL.md").write_text(f"# {unused}\nUNUSED_SKILL_CONTENT\n", encoding="utf-8")

            context = agent_loop.load_skill_context(
                root,
                {
                    "task": {"name": "omnidocbench_v1_6", "skill": "omnidocbench_task"},
                    "inference": {"skill": "lmms-eval-old"},
                    "evaluation": {"skill": "omnidocbench"},
                },
            )

        joined = json.dumps(context, ensure_ascii=False, sort_keys=True)
        self.assertIn("task/omnidocbench_task", joined)
        self.assertIn("inference/lmms-eval-old", joined)
        self.assertIn("evaluation/omnidocbench", joined)
        self.assertIn("ACTIVE_SKILL_CONTENT", joined)
        self.assertNotIn("UNUSED_SKILL_CONTENT", joined)

    def test_agent_tools_expose_command_line_tool(self):
        tools = agent_loop.build_tools()
        names = [tool["function"]["name"] for tool in tools]

        self.assertIn("run_command", names)
        self.assertIn("start_long_command", names)
        self.assertIn("wait_long_command", names)
        self.assertIn("inspect_long_command", names)
        self.assertIn("extract_lmms_eval_samples", names)
        self.assertIn("extract_omnidocbench_metrics", names)
        self.assertIn("finish", names)
        run_command = next(tool for tool in tools if tool["function"]["name"] == "run_command")
        self.assertIn("argv", run_command["function"]["parameters"]["required"])
        start_long_command = next(tool for tool in tools if tool["function"]["name"] == "start_long_command")
        self.assertIn("argv", start_long_command["function"]["parameters"]["required"])

    def test_extract_lmms_eval_samples_from_ansi_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_path = root / "logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl"
            sample_path.parent.mkdir(parents=True)
            sample_path.write_text('{"sample_id":"1"}\n', encoding="utf-8")
            log_text = (
                "\x1b[32m2026-06-29 22:16:43.325\x1b[0m | INFO | "
                "\x1b[1mResults saved in logs/qwen3_5_vllm/omnidocbench_v1_6/"
                "20260629_204704_samples_omnidocbench_v1_6.jsonl\x1b[0m\n"
                ">>> Evaluation complete. Logs saved to: ./logs/qwen3_5_vllm/omnidocbench_v1_6\n"
            )

            result = agent_loop.execute_action(
                {
                    "action": "extract_lmms_eval_samples",
                    "text": log_text,
                    "cwd": str(root),
                    "task": "omnidocbench_v1_6",
                },
                workspace=root,
            )

        self.assertEqual(result["samples_jsonl"], "logs/qwen3_5_vllm/omnidocbench_v1_6/20260629_204704_samples_omnidocbench_v1_6.jsonl")
        self.assertEqual(result["samples_jsonl_abs"], str(sample_path.resolve()))
        self.assertEqual(result["next_skill_input"]["prediction_jsonl"], str(sample_path.resolve()))
        self.assertEqual(result["next_skill_input"]["task"], "omnidocbench_v1_6")

    def test_extract_lmms_eval_samples_fails_when_artifact_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(agent_loop.AgentLoopError):
                agent_loop.execute_action(
                    {
                        "action": "extract_lmms_eval_samples",
                        "text": "Results saved in logs/qwen3_5_vllm/omnidocbench_v1_6/missing_samples_omnidocbench_v1_6.jsonl",
                        "cwd": str(root),
                    },
                    workspace=root,
                )

    def test_extract_omnidocbench_metrics_writes_markdown_report_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.md"
            log_text = """
========== END_FINAL_EVAL_RUN_REPORT 20260702_140820_samples_omnidocbench_v1_6_quick_match ==========
[notebook_metric_summary]
  text_block_Edit_dist: 0.09570624547098938
  display_formula_CDM: 91.11259459002511
  table_TEDS: 67.91812720778336
  table_TEDS_structure_only: 71.78252019172675
  reading_order_Edit_dist: 0.20022868421853282
  overall_notebook: 83.1533657502365
[final-eval-run-report] saved to ./result/20260702_140820_samples_omnidocbench_v1_6_quick_match_run_summary.json
[runtime-environment-json] saved to ./result/20260702_140820_samples_omnidocbench_v1_6_quick_match_runtime_environment.json
[runtime-environment-log] saved to ./result/20260702_140820_samples_omnidocbench_v1_6_quick_match_runtime_environment.log
[stage-execution-json] saved to ./result/20260702_140820_samples_omnidocbench_v1_6_quick_match_stage_execution.json
[stage-execution-log] saved to ./result/20260702_140820_samples_omnidocbench_v1_6_quick_match_stage_execution.log
"""

            result = agent_loop.execute_action(
                {
                    "action": "extract_omnidocbench_metrics",
                    "text": log_text,
                    "cwd": str(root),
                    "markdown_path": str(report_path),
                },
                workspace=root,
            )

            markdown = report_path.read_text(encoding="utf-8")

        self.assertEqual(result["run_id"], "20260702_140820_samples_omnidocbench_v1_6_quick_match")
        self.assertEqual(result["metrics"]["overall_notebook"], 83.1533657502365)
        self.assertEqual(result["metrics"]["table_TEDS"], 67.91812720778336)
        self.assertIn("| overall_notebook | 83.1533657502365 |", result["metrics_markdown"])
        self.assertIn("| text_block_Edit_dist | 0.09570624547098938 |", markdown)
        self.assertTrue(result["report_files"]["final-eval-run-report"].endswith("_run_summary.json"))

    def test_extract_omnidocbench_metrics_fails_without_summary_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(agent_loop.AgentLoopError):
                agent_loop.execute_action(
                    {
                        "action": "extract_omnidocbench_metrics",
                        "text": "no metrics here",
                        "cwd": str(root),
                    },
                    workspace=root,
                )

    def test_write_tools_are_restricted_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            outside = Path(tmp) / "outside.txt"
            root.mkdir()

            ok = agent_loop.execute_action(
                {
                    "action": "write_file",
                    "path": str(root / "report.md"),
                    "content": "ok",
                },
                workspace=root,
            )

            with self.assertRaises(agent_loop.AgentLoopError):
                agent_loop.execute_action(
                    {
                        "action": "write_file",
                        "path": str(outside),
                        "content": "no",
                    },
                    workspace=root,
                )

        self.assertEqual(ok["path"], str((root / "report.md").resolve()))

    def test_long_command_metadata_is_restricted_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            outside = Path(tmp) / "outside-commands"
            root.mkdir()

            with self.assertRaises(agent_loop.AgentLoopError):
                agent_loop.execute_action(
                    {
                        "action": "start_long_command",
                        "argv": [sys.executable, "-c", "print('should-not-run')"],
                        "cwd": str(root),
                        "commands_dir": str(outside),
                    },
                    workspace=root,
                )

        self.assertFalse(outside.exists())

    def test_metric_markdown_path_is_restricted_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            outside = Path(tmp) / "report.md"
            root.mkdir()
            log_text = """
[notebook_metric_summary]
  text_block_Edit_dist: 0.1
  display_formula_CDM: 90
  table_TEDS: 70
  table_TEDS_structure_only: 72
  reading_order_Edit_dist: 0.2
  overall_notebook: 83
"""

            with self.assertRaises(agent_loop.AgentLoopError):
                agent_loop.execute_action(
                    {
                        "action": "extract_omnidocbench_metrics",
                        "text": log_text,
                        "cwd": str(root),
                        "markdown_path": str(outside),
                    },
                    workspace=root,
                )

        self.assertFalse(outside.exists())

    def test_long_command_tools_support_generic_evaluation_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            start = agent_loop.execute_action(
                {
                    "action": "start_long_command",
                    "argv": [sys.executable, "-c", "import time; time.sleep(0.2); print('metric-ready')"],
                    "cwd": str(root),
                    "skill_type": "evaluation",
                    "label": "toy-benchmark",
                },
                workspace=root,
            )
            result = agent_loop.execute_action(
                {
                    "action": "wait_long_command",
                    "command_id": start["command_id"],
                    "timeout_sec": 5,
                },
                workspace=root,
            )
            self.assertEqual(start["action"], "start_long_command")
            self.assertEqual(start["status"], "running")
            self.assertEqual(start["skill_type"], "evaluation")
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["returncode"], 0)
            self.assertIn("metric-ready", result["log_tail"])
            self.assertTrue(Path(result["log_path"]).exists())
            self.assertTrue(Path(result["metadata_path"]).exists())

    def test_long_command_tools_report_failed_evaluation_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            start = agent_loop.execute_action(
                {
                    "action": "start_long_command",
                    "argv": [
                        sys.executable,
                        "-c",
                        "import sys; print('benchmark failed', file=sys.stderr); raise SystemExit(7)",
                    ],
                    "cwd": str(root),
                    "skill_type": "evaluation",
                    "label": "toy-benchmark",
                },
                workspace=root,
            )
            result = agent_loop.execute_action(
                {
                    "action": "wait_long_command",
                    "command_id": start["command_id"],
                    "timeout_sec": 5,
                },
                workspace=root,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["returncode"], 7)
        self.assertIsNone(result["signal"])
        self.assertIn("benchmark failed", result["log_tail"])

    def test_long_command_wait_recovers_after_starting_agent_process_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            starter = (
                "import json, pathlib, sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "import agent_loop\n"
                "workspace = pathlib.Path(sys.argv[2])\n"
                "result = agent_loop.execute_action({\n"
                "    'action': 'start_long_command',\n"
                "    'argv': [sys.executable, '-c', \"import time; time.sleep(0.2); print('recoverable-done')\"],\n"
                "    'cwd': str(workspace),\n"
                "    'skill_type': 'evaluation',\n"
                "    'label': 'recoverable-benchmark',\n"
                "}, workspace=workspace)\n"
                "print(json.dumps(result, sort_keys=True))\n"
            )
            completed = subprocess.run(
                [sys.executable, "-B", "-c", starter, str(Path.cwd()), str(root)],
                text=True,
                capture_output=True,
                check=True,
            )
            start = json.loads(completed.stdout)

            result = agent_loop.execute_action(
                {
                    "action": "wait_long_command",
                    "command_id": start["command_id"],
                    "metadata_path": start["metadata_path"],
                    "timeout_sec": 5,
                },
                workspace=root,
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("recoverable-done", result["log_tail"])

    def test_wait_long_command_emits_heartbeat_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress_events = []
            start = agent_loop.execute_action(
                {
                    "action": "start_long_command",
                    "argv": [sys.executable, "-c", "import time; time.sleep(0.3); print('done')"],
                    "cwd": str(root),
                    "skill_type": "evaluation",
                    "label": "heartbeat-benchmark",
                },
                workspace=root,
            )

            result = agent_loop.execute_action(
                {
                    "action": "wait_long_command",
                    "command_id": start["command_id"],
                    "timeout_sec": 5,
                    "heartbeat_sec": 0.05,
                },
                workspace=root,
                progress=progress_events.append,
            )

        self.assertEqual(result["status"], "succeeded")
        joined = "\n".join(progress_events)
        self.assertIn("long_command_wait", joined)
        self.assertIn(start["command_id"], joined)

    def test_cancel_active_long_commands_terminates_running_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            start = agent_loop.execute_action(
                {
                    "action": "start_long_command",
                    "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
                    "cwd": str(root),
                    "skill_type": "evaluation",
                    "label": "interruptible-benchmark",
                },
                workspace=root,
            )

            cancelled = agent_loop.cancel_active_long_commands(grace_sec=0.2)
            result = agent_loop.execute_action(
                {
                    "action": "inspect_long_command",
                    "command_id": start["command_id"],
                    "metadata_path": start["metadata_path"],
                },
                workspace=root,
            )

        self.assertEqual(len(cancelled), 1)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["command_id"], start["command_id"])

    def test_cli_can_generate_job_from_checkpoint_task_and_report_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "report"
            args = agent_cli.parse_args(
                [
                    "--base-url",
                    "http://127.0.0.1:8001/v1",
                    "--agent-model",
                    "qwen3-5",
                    "--checkpoint",
                    "/models/checkpoint-a",
                    "--task",
                    "omnidocbench_v1_6",
                    "--report-dir",
                    str(report_dir),
                ]
            )
            runtime = agent_cli.prepare_runtime(args)
            job = json.loads(runtime.job_path.read_text(encoding="utf-8"))

        self.assertEqual(job["agent"]["model"], "qwen3-5")
        self.assertEqual(job["checkpoint"]["path"], "/models/checkpoint-a")
        self.assertEqual(job["task"]["name"], "omnidocbench_v1_6")
        self.assertEqual(job["task"]["skill"], "omnidocbench_task")
        self.assertEqual(job["evaluation"]["skill"], "omnidocbench")
        self.assertEqual(job["outputs"]["report_dir"], str(report_dir.resolve()))
        self.assertEqual(runtime.state_path, report_dir.resolve() / "agent_state.json")
        self.assertEqual(runtime.workspace, report_dir.resolve())

    def test_generated_lmms_eval_old_job_rejects_agent_on_local_port_8000(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "report"
            args = agent_cli.parse_args(
                [
                    "--base-url",
                    "http://127.0.0.1:8000/v1",
                    "--agent-model",
                    "qwen-agent",
                    "--checkpoint",
                    "/models/checkpoint-a",
                    "--task",
                    "omnidocbench_v1_6",
                    "--report-dir",
                    str(report_dir),
                    "--inference-skill",
                    "lmms-eval-old",
                ]
            )

            with self.assertRaisesRegex(agent_loop.AgentLoopError, "port 8000"):
                agent_cli.prepare_runtime(args)

    def test_cli_records_worker_cuda_visible_devices_in_generated_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "report"
            args = agent_cli.parse_args(
                [
                    "--base-url",
                    "http://127.0.0.1:6666/v1",
                    "--agent-model",
                    "qwen-agent",
                    "--checkpoint",
                    "/models/checkpoint-a",
                    "--task",
                    "omnidocbench_v1_6",
                    "--report-dir",
                    str(report_dir),
                    "--worker-cuda-visible-devices",
                    "0,1",
                ]
            )
            runtime = agent_cli.prepare_runtime(args)
            job = json.loads(runtime.job_path.read_text(encoding="utf-8"))

        self.assertEqual(job["runtime"]["worker_cuda_visible_devices"], "0,1")

    def test_cli_worker_cuda_visible_devices_updates_process_environment(self):
        args = agent_cli.parse_args(
            [
                "--base-url",
                "http://127.0.0.1:6666/v1",
                "--agent-model",
                "qwen-agent",
                "--checkpoint",
                "/models/checkpoint-a",
                "--task",
                "omnidocbench_v1_6",
                "--report-dir",
                "report",
                "--worker-cuda-visible-devices",
                "0,1",
            ]
        )
        env = {}

        agent_cli.apply_worker_environment(args, env=env)

        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0,1")

    def test_cli_worker_environment_adds_local_no_proxy_entries(self):
        args = agent_cli.parse_args(
            [
                "--base-url",
                "http://127.0.0.1:6666/v1",
                "--agent-model",
                "qwen-agent",
                "--checkpoint",
                "/models/checkpoint-a",
                "--task",
                "omnidocbench_v1_6",
                "--report-dir",
                "report",
            ]
        )
        env = {"NO_PROXY": "example.com", "no_proxy": "foo.local"}

        agent_cli.apply_worker_environment(args, env=env)

        for key in ("NO_PROXY", "no_proxy"):
            self.assertIn("127.0.0.1", env[key])
            self.assertIn("localhost", env[key])
            self.assertEqual(env[key].count("127.0.0.1"), 1)

    def test_agent_openai_client_does_not_use_environment_proxies(self):
        source = Path("eval_agent_loop/client.py").read_text(encoding="utf-8")

        self.assertIn("import httpx", source)
        self.assertIn("httpx.Client(trust_env=False)", source)
        self.assertIn("http_client=", source)

    def test_lmms_eval_old_skill_uses_batch_size_32(self):
        skill = Path("SKILLS/inference/lmms-eval-old/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Pass batch size `32` explicitly", skill)
        self.assertIn('"32"', skill)
        self.assertNotIn('"omnidocbench_v1_6" "4"', skill)

    def test_omnidocbench_task_skill_documents_inference_then_evaluation_chain(self):
        skill = Path("SKILLS/task/omnidocbench_task/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("lmms-eval-old", skill)
        self.assertIn("omnidocbench", skill)
        self.assertIn("start_long_command", skill)
        self.assertIn("wait_long_command", skill)
        self.assertIn("extract_lmms_eval_samples", skill)
        self.assertIn("extract_omnidocbench_metrics", skill)
        self.assertLess(skill.index("extract_lmms_eval_samples"), skill.index("extract_omnidocbench_metrics"))

    def test_lmms_eval_old_script_checks_root_health_without_proxy(self):
        script = Path("lmms-eval-old/scripts/evaluate_qwen3_5_vllm.sh").read_text(encoding="utf-8")

        self.assertIn('HEALTH_URL="http://127.0.0.1:${BASE_PORT}/health"', script)
        self.assertIn('API_BASE="http://127.0.0.1:${BASE_PORT}/v1"', script)
        self.assertIn('curl --noproxy "*"', script)
        self.assertNotIn('${url}/health', script)

    def test_lmms_eval_old_cleanup_does_not_kill_all_gpu_processes(self):
        script = Path("lmms-eval-old/scripts/evaluate_qwen3_5_vllm.sh").read_text(encoding="utf-8")

        self.assertNotIn("fuser -k -9 /dev/nvidia*", script)

    def test_qwen3_5_vllm_client_does_not_use_environment_proxies(self):
        source = Path("lmms-eval-old/lmms_eval/models/qwen3_5_vllm.py").read_text(encoding="utf-8")

        self.assertIn("import httpx", source)
        self.assertIn("httpx.AsyncClient(trust_env=False)", source)
        self.assertIn("http_client=", source)
        self.assertIn("{type(e).__name__}: {e!r}", source)

    def test_run_loop_executes_tool_calls_and_continues_until_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = skills_dir / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nreal instructions\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text('{"run_id":"job-1"}', encoding="utf-8")
            state_path = root / "state.json"

            client = ScriptedToolClient(
                [
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                "call_1",
                                "run_command",
                                {"argv": ["python3", "-c", "print('tool-ok')"], "cwd": str(root), "timeout_sec": 10},
                            )
                        ],
                    ),
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall("call_2", "finish", {"message": "finished after tool"})
                        ],
                    ),
                ]
            )

            result = agent_loop.run_loop(
                client=client,
                config=agent_loop.AgentConfig(base_url="http://example.test/v1", api_key="EMPTY", max_iterations=5),
                skills_dir=skills_dir,
                job_path=job_path,
                state_path=state_path,
                workspace=root,
            )

        self.assertEqual(result["action"], "finish")
        self.assertEqual(result["message"], "finished after tool")
        self.assertEqual(len(client.calls), 2)
        second_messages = client.calls[1]["messages"]
        self.assertTrue(any(message.get("role") == "tool" and "tool-ok" in message.get("content", "") for message in second_messages))

    def test_run_loop_emits_progress_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = skills_dir / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nreal instructions\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text('{"run_id":"job-1"}', encoding="utf-8")
            state_path = root / "state.json"
            progress_events = []

            client = ScriptedToolClient(
                [
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                "call_1",
                                "run_command",
                                {"argv": [sys.executable, "-c", "print('tool-ok')"], "cwd": str(root), "timeout_sec": 10},
                            )
                        ],
                    ),
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall("call_2", "finish", {"message": "done"})
                        ],
                    ),
                ]
            )

            result = agent_loop.run_loop(
                client=client,
                config=agent_loop.AgentConfig(base_url="http://example.test/v1", api_key="EMPTY", max_iterations=5),
                skills_dir=skills_dir,
                job_path=job_path,
                state_path=state_path,
                workspace=root,
                progress=progress_events.append,
            )

        self.assertEqual(result["message"], "done")
        joined = "\n".join(progress_events)
        self.assertIn("agent_start", joined)
        self.assertIn("model_request", joined)
        self.assertIn("tool_batch_start", joined)
        self.assertIn("run_command", joined)
        self.assertIn("tool_result", joined)
        self.assertIn("agent_stop", joined)

    def test_run_loop_executes_same_turn_tool_calls_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "SKILLS"
            for name in ("inference", "evaluation", "task"):
                skill_dir = skills_dir / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"# {name}\nreal instructions\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text('{"run_id":"job-1"}', encoding="utf-8")
            state_path = root / "state.json"
            script = (
                "import pathlib, sys, time\n"
                "root = pathlib.Path(sys.argv[1])\n"
                "own = root / sys.argv[2]\n"
                "other = root / sys.argv[3]\n"
                "own.write_text('ready', encoding='utf-8')\n"
                "deadline = time.time() + 2\n"
                "while time.time() < deadline:\n"
                "    if other.exists():\n"
                "        print('saw-' + sys.argv[3])\n"
                "        raise SystemExit(0)\n"
                "    time.sleep(0.02)\n"
                "print('missing-' + sys.argv[3], file=sys.stderr)\n"
                "raise SystemExit(3)\n"
            )

            client = ScriptedToolClient(
                [
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                "call_a",
                                "run_command",
                                {
                                    "argv": [sys.executable, "-c", script, str(root), "a.ready", "b.ready"],
                                    "cwd": str(root),
                                    "timeout_sec": 5,
                                },
                            ),
                            ToolCall(
                                "call_b",
                                "run_command",
                                {
                                    "argv": [sys.executable, "-c", script, str(root), "b.ready", "a.ready"],
                                    "cwd": str(root),
                                    "timeout_sec": 5,
                                },
                            ),
                        ],
                    ),
                    agent_loop.AssistantTurn(
                        content=None,
                        tool_calls=[
                            ToolCall("call_3", "finish", {"message": "finished after parallel tools"})
                        ],
                    ),
                ]
            )

            result = agent_loop.run_loop(
                client=client,
                config=agent_loop.AgentConfig(base_url="http://example.test/v1", api_key="EMPTY", max_iterations=5),
                skills_dir=skills_dir,
                job_path=job_path,
                state_path=state_path,
                workspace=root,
            )

        self.assertEqual(result["message"], "finished after parallel tools")
        first_tool_messages = [
            message for message in client.calls[1]["messages"]
            if message.get("role") == "tool"
        ]
        self.assertEqual(len(first_tool_messages), 2)
        self.assertTrue(all('"returncode": 0' in message["content"] for message in first_tool_messages))

    def test_command_line_script_exists(self):
        script = Path("bin/eval-agent")
        self.assertTrue(script.exists())
        self.assertTrue(os.access(script, os.X_OK))


if __name__ == "__main__":
    unittest.main()
