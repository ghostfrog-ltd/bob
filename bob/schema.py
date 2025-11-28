from __future__ import annotations

BOB_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {
            "type": "string",
            "enum": ["codemod", "analysis", "tool", "chat"],
        },
        "summary": {"type": "string"},
        "analysis_file": {
            "type": "string",
            "default": "",
        },
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": [
                            "prepend_comment",
                            "create_or_overwrite_file",
                            "append_to_bottom",
                        ],
                    },
                    "content": {"type": "string"},
                },
                "required": ["file", "operation", "content"],
                "additionalProperties": False,
            },
        },
        "tool": {
            "type": "object",
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
