# chad/tools/__init__.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

ToolResult = Tuple[str, str]  # (tool_result, message)

ToolFn = Callable[
    [Dict[str, Any], Path, Path, Path],
    ToolResult,
]

_TOOL_IMPLS: Dict[str, ToolFn] = {}


def register_tool(name: str, fn: ToolFn) -> None:
    """Register a tool implementation under a given name."""
    _TOOL_IMPLS[name] = fn


def run_tool(
    name: str,
    args: Dict[str, Any],
    *,
    project_root: Path,
    notes_dir: Path,
    scratch_dir: Path,
) -> Optional[ToolResult]:
    """
    Look up a tool in the registry and run it.

    Returns:
      (tool_result, message) if the tool exists, or
      None if the tool name is unknown to Chad.
    """
    fn = _TOOL_IMPLS.get(name)
    if fn is None:
        return None

    return fn(args, project_root, notes_dir, scratch_dir)


# Import tool modules so their register_tool() calls run at import time.
# (Order does not matter, they just populate _TOOL_IMPLS.)
from . import get_current_datetime_tool  # noqa: F401
from . import list_files_tool  # noqa: F401
from . import read_file_tool  # noqa: F401
from . import markdown_notes_tool  # noqa: F401
from . import send_email_tool  # noqa: F401
from . import run_python_script_tool  # noqa: F401
