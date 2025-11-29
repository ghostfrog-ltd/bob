# chad/tools/read_file_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from helpers.jail import resolve_in_project_jail

from . import register_tool, ToolResult


def _run_read_file(
    args: Dict[str, Any],
    project_root: Path,
    notes_dir: Path,    # unused
    scratch_dir: Path,  # unused
) -> ToolResult:
    rel_path = str(
        args.get("path")
        or args.get("file")
        or ""
    )
    try:
        max_chars = int(args.get("max_chars", 16000))
    except (TypeError, ValueError):
        max_chars = 16000

    target_path = resolve_in_project_jail(rel_path, project_root)
    if target_path is None or not target_path.exists() or not target_path.is_file():
        message = (
            f"Chad tried to read_file {rel_path!r} but it does not exist, "
            "is not a file, or is outside the project jail."
        )
        return "", message

    try:
        raw = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        message = (
            f"Chad tried to read_file {rel_path!r} but it is not UTF-8 text."
        )
        return "", message

    if len(raw) > max_chars:
        tool_result = raw[:max_chars] + "\n\n... (truncated)"
    else:
        tool_result = raw
    message = f"Chad read_file {rel_path!r} (up to {max_chars} chars)."
    return tool_result, message


register_tool("read_file", _run_read_file)
