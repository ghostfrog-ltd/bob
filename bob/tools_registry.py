# bob/tools_registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ToolSpec:
    name: str
    description: str
    args_schema: Dict[str, Any]


# Single source of truth for all tool names + their args.
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "get_current_datetime": ToolSpec(
        name="get_current_datetime",
        description="Return the current local date/time as a human-readable string.",
        args_schema={}
    ),
    "list_files": ToolSpec(
        name="list_files",
        description=(
            "List files/directories under a given path inside the project jail. "
            "Useful to explore the codebase or find a file."
        ),
        args_schema={
            "path": {
                "type": "string",
                "required": False,
                "default": ".",
                "description": "Relative path from project root."
            },
            "recursive": {
                "type": "boolean",
                "required": False,
                "default": False,
                "description": "Whether to recurse into subdirectories."
            },
            "max_entries": {
                "type": "integer",
                "required": False,
                "default": 200,
                "description": "Maximum number of entries to list."
            },
        },
    ),
    "read_file": ToolSpec(
        name="read_file",
        description="Read a UTF-8 text file from inside the project jail.",
        args_schema={
            "path": {
                "type": "string",
                "required": True,
                "description": "Relative path from project root to the file.",
            },
            "max_chars": {
                "type": "integer",
                "required": False,
                "default": 16000,
                "description": "Maximum number of characters to return.",
            },
        },
    ),
    "create_markdown_note": ToolSpec(
        name="create_markdown_note",
        description="Create a markdown note in the notes/ directory.",
        args_schema={
            "title": {
                "type": "string",
                "required": True,
                "description": "Human title for the note.",
            },
            "content": {
                "type": "string",
                "required": True,
                "description": "Markdown body to write to the note.",
            },
        },
    ),
    "append_to_markdown_note": ToolSpec(
        name="append_to_markdown_note",
        description="Append content to an existing markdown note, or create it if missing.",
        args_schema={
            "title": {
                "type": "string",
                "required": True,
                "description": "Title (same as used when creating).",
            },
            "content": {
                "type": "string",
                "required": True,
                "description": "Markdown content to append.",
            },
        },
    ),
    "send_email": ToolSpec(
        name="send_email",
        description=(
            "Send an email using SMTP_* env vars. ALWAYS sends to SMTP_TO/SMTP_TEST_TO "
            "ignoring user-supplied 'to'. Can attach files inside the project."
        ),
        args_schema={
            "subject": {
                "type": "string",
                "required": False,
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "required": False,
                "description": "Plain text email body.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "required": False,
                "description": (
                    "List of relative file paths to attach. If omitted, the most recent "
                    "markdown note will be auto-attached (FAST EMAIL RULE)."
                ),
            },
        },
    ),
    # Example: your “script_to_add_comments.py” could be exposed like this:
    "run_python_script": ToolSpec(
        name="run_python_script",
        description=(
            "Run a Python script inside the project (e.g. script_to_add_comments.py). "
            "Use this instead of inventing per-script tools."
        ),
        args_schema={
            "path": {
                "type": "string",
                "required": True,
                "description": "Relative path of the script, e.g. 'script_to_add_comments.py'.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "required": False,
                "description": "Optional argv-style arguments for the script.",
            },
        },
    ),
}


def describe_tools_for_prompt() -> str:
    """
    Render a human-friendly description block that can be pasted into
    Bob's system prompt so he knows what tools exist and how to call them.
    """
    lines: list[str] = []
    lines.append("AVAILABLE TOOLS\n")
    for spec in TOOL_REGISTRY.values():
        lines.append(f"- {spec.name}: {spec.description}")
        if spec.args_schema:
            lines.append("  Args:")
            for arg_name, meta in spec.args_schema.items():
                req = "required" if meta.get("required") else "optional"
                default = meta.get("default")
                default_str = f" (default={default!r})" if default is not None else ""
                lines.append(
                    f"    - {arg_name} ({meta.get('type')} {req}{default_str}): "
                    f"{meta.get('description', '').rstrip()}"
                )
        lines.append("")  # blank line between tools
    return "\n".join(lines).strip()
