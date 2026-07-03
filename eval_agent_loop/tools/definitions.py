from __future__ import annotations

from typing import Any


ALLOWED_ACTIONS = {
    "run_command",
    "start_long_command",
    "wait_long_command",
    "inspect_long_command",
    "read_file",
    "write_file",
    "append_file",
    "append_event",
    "finish",
    "ask_user",
}
FORBIDDEN_ACTION_WORDS = ("simulate", "mock", "fake", "stub")


def build_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a real command without a shell. Use argv as an argument vector.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "cwd": {"type": "string"},
                        "env": {"type": "object", "additionalProperties": {"type": "string"}},
                        "timeout_sec": {"type": "number", "minimum": 1},
                    },
                    "required": ["argv"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_long_command",
                "description": "Start a real long-running inference, evaluation, benchmark, or service command in the background.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "cwd": {"type": "string"},
                        "env": {"type": "object", "additionalProperties": {"type": "string"}},
                        "command_id": {"type": "string"},
                        "commands_dir": {"type": "string"},
                        "log_path": {"type": "string"},
                        "label": {"type": "string"},
                        "skill_type": {"type": "string", "enum": ["inference", "evaluation", "task", "service"]},
                    },
                    "required": ["argv"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "wait_long_command",
                "description": "Wait for a long command started by this agent process and return exit status plus log tail.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command_id": {"type": "string"},
                        "commands_dir": {"type": "string"},
                        "metadata_path": {"type": "string"},
                        "timeout_sec": {"type": "number", "minimum": 1},
                        "heartbeat_sec": {"type": "number", "minimum": 0.01},
                    },
                    "required": ["command_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "inspect_long_command",
                "description": "Inspect persisted status and log tail for a long-running inference, evaluation, task, or service command.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command_id": {"type": "string"},
                        "commands_dir": {"type": "string"},
                        "metadata_path": {"type": "string"},
                    },
                    "required": ["command_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read bytes from a real UTF-8 compatible file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write text to a real file, creating parent directories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "append_file",
                "description": "Append text to a real file, creating parent directories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "append_event",
                "description": "Append one JSON event line to a real events.jsonl file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "event": {"type": "object"},
                    },
                    "required": ["path", "event"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Stop the loop and ask the user a specific blocking question.",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish",
                "description": "Stop the loop with a concise final summary based only on real artifacts.",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                },
            },
        },
    ]
