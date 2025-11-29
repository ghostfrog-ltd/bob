# bob/tools_registry.py
"""
Central registry for all tools Bob is allowed to call.

Each entry documents:
- impl:       Name of the function Chad should dispatch to
- description:Human-readable explanation of what the tool does
- example:    Example arguments Bob may pass

This registry is used:
- To build the system prompt (describe_tools_for_prompt)
- To validate tool names
- To enforce consistency across Bob → Chad → local executor
"""

TOOL_REGISTRY = {
    "run_python_script": {
        "impl": "run_python_script",
        "description": (
            "Execute a Python script located inside the project jail. "
            "Arguments must be a list of strings. Path must be relative."
        ),
        "example": {
            "path": "scripts/example_script.py",
            "args": ["--option1", "value1"],
        },
    },

    "list_files": {
        "impl": "list_files",
        "description": (
            "List files under a directory relative to the project root. "
            "Supports recursive and non-recursive modes."
        ),
        "example": {
            "path": "src",
            "recursive": False,
            "max_entries": 200,
        },
    },

    "read_file": {
        "impl": "read_file",
        "description": (
            "Read the contents of a file inside the project jail. "
            "Supports max_chars truncation for safety."
        ),
        "example": {
            "path": "README.md",
            "max_chars": 16000,
        },
    },

    "create_markdown_note": {
        "impl": "create_markdown_note",
        "description": (
            "Create a new markdown note inside /data/notes/. "
            "Automatically slugifies the title to form the filename."
        ),
        "example": {
            "title": "Meeting Notes",
            "body": "## Agenda\n- Item 1\n- Item 2",
        },
    },

    "append_to_markdown_note": {
        "impl": "append_to_markdown_note",
        "description": (
            "Append text to an existing markdown note. "
            "If it does not exist, it will be created."
        ),
        "example": {
            "title": "Meeting Notes",
            "body": "\nAdditional discussion points.",
        },
    },

    "send_email": {
        "impl": "send_email",
        "description": (
            "Send an email using SMTP settings from the environment. "
            "Recipient is ALWAYS forced to SMTP_TO; user-supplied 'to' is ignored."
        ),
        "example": {
            "subject": "Daily Report",
            "body": "Here is the latest report.",
        },
    },

    "get_current_datetime": {
        "impl": "get_current_datetime",
        "description": "Return the system's current local date/time as a formatted string.",
        "example": {},
    },
}
