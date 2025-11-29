# bob/schema.py
from __future__ import annotations

"""
Schema definition for Bob's planning output.

This JSON schema is used as a *contract* for the object Bob should emit when
building a plan for Chad to execute. It is referenced in prompts and can also
be used for validation on the Python side if desired.
"""

BOB_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {
            "type": "string",
            "enum": ["codemod", "analysis", "tool", "chat"],
        },
        "summary": {
            "type": "string",
            "description": "Short natural-language description of what Bob/Chad will do.",
        },
        "analysis_file": {
            "type": "string",
            "default": "",
            "description": "Relative path to a file to analyse (for 'analysis' tasks), or empty.",
        },
        "edits": {
            "type": "array",
            "description": "List of codemod-style edits for Chad to apply.",
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Relative path to the target file inside the project jail.",
                    },
                    "operation": {
                        "type": "string",
                        "enum": [
                            "prepend_comment",
                            "create_or_overwrite_file",
                            "append_to_bottom",
                        ],
                    },
                    "content": {
                        "type": "string",
                        "description": "Content payload for the chosen operation.",
                    },
                },
                "required": ["file", "operation", "content"],
                "additionalProperties": False,
            },
        },
        "tool": {
            "type": "object",
            "description": "Tool call description when task_type='tool'. Empty otherwise.",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": [
                        "get_current_datetime",
                        "list_files",
                        "read_file",
                        "create_markdown_note",
                        "append_to_markdown_note",
                        "send_email",
                    ],
                },
                "args": {
                    "type": "object",
                    "additionalProperties": True,
                    "default": {},
                },
            },
            "default": {},
        },
    },
    "required": ["task_type", "summary", "analysis_file", "edits"],
    "additionalProperties": False,
}
