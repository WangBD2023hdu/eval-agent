#!/usr/bin/env python3
"""Compatibility facade for the eval_agent_loop package."""

from eval_agent_loop import (
    AgentConfig,
    AgentLoopError,
    AssistantTurn,
    OpenAIChatClient,
    ToolExecution,
    build_messages,
    build_tools,
    execute_action,
    execute_tool_call_batch,
    extract_lmms_eval_samples,
    extract_omnidocbench_metrics,
    inspect_long_command,
    load_skill_bundle,
    load_structured_file,
    parse_model_action,
    parse_tool_call,
    read_state,
    run_loop,
    start_long_command,
    tool_call_to_message,
    validate_action,
    wait_long_command,
    write_state,
)
from eval_agent_loop.cli import entrypoint, main

__all__ = [
    "AgentConfig",
    "AgentLoopError",
    "AssistantTurn",
    "OpenAIChatClient",
    "ToolExecution",
    "build_messages",
    "build_tools",
    "execute_action",
    "execute_tool_call_batch",
    "extract_lmms_eval_samples",
    "extract_omnidocbench_metrics",
    "inspect_long_command",
    "entrypoint",
    "load_skill_bundle",
    "load_structured_file",
    "main",
    "parse_model_action",
    "parse_tool_call",
    "read_state",
    "run_loop",
    "start_long_command",
    "tool_call_to_message",
    "validate_action",
    "wait_long_command",
    "write_state",
]


if __name__ == "__main__":
    raise SystemExit(entrypoint())
