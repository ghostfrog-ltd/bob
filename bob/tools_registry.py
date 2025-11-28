# bob/tools_registry.py
# This file defines the TOOL_REGISTRY dictionary mapping tool names to their implementations,
# descriptions, and example payloads to ensure accurate and up-to-date use across the system.

TOOL_REGISTRY = {
    "run_python_script": {
        "impl": "run_python_script",
        "description": "Run a Python script from the project root with optional CLI arguments.",
        "example": {
            "path": "scripts/example_script.py",
            "args": ["--option1", "value1"]
        }
    },
    "list_files": {
        "impl": "list_files",
        "description": "List files in a given directory relative to the project root.",
        "example": {
            "dir": "src"
        }
    },
    "read_file": {
        "impl": "read_file",
        "description": "Read the contents of a file relative to the project root.",
        "example": {
            "path": "README.md"
        }
    },
    "create_markdown_note": {
        "impl": "create_markdown_note",
        "description": "Create a new markdown note with specified content.",
        "example": {
            "title": "Meeting Notes",
            "body": "## Agenda\n- Item 1\n- Item 2"
        }
    },
    "append_to_markdown_note": {
        "impl": "append_to_markdown_note",
        "description": "Append content to an existing markdown note.",
        "example": {
            "title": "Meeting Notes",
            "body": "\nAdditional discussion points."
        }
    },
    "send_email": {
        "impl": "send_email",
        "description": "Send an email via configured SMTP using environment recipient; 'to' field is ignored.",
        "example": {
            "subject": "Daily Report",
            "body": "Here is the latest report."
        }
    },
    "get_current_datetime": {
        "impl": "get_current_datetime",
        "description": "Get the current date and time in ISO format.",
        "example": {}
    }
}

# Ensure this registry is kept in sync with actual tool implementations to avoid drift and reduce errors.
