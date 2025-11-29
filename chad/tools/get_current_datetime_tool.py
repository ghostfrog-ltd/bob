# chad/tools/get_current_datetime_tool.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from . import register_tool, ToolResult


def _run_get_current_datetime(
    args: Dict[str, Any],
    project_root: Path,  # unused
    notes_dir: Path,     # unused
    scratch_dir: Path,   # unused
) -> ToolResult:
    now_local = datetime.now().astimezone()
    dt_str = now_local.strftime("%A, %d %B %Y, %H:%M:%S %Z (%z)")
    tool_result = f"Local system date and time: {dt_str}"
    message = "Chad ran tool 'get_current_datetime' using the system clock."
    return tool_result, message


register_tool("get_current_datetime", _run_get_current_datetime)
