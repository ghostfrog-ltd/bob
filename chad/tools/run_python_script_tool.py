# chad/tools/run_python_script_tool.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

from helpers.jail import resolve_in_project_jail

from . import register_tool, ToolResult


def _run_python_script(
    args: Dict[str, Any],
    project_root: Path,
    notes_dir: Path,    # unused
    scratch_dir: Path,  # unused
) -> ToolResult:
    rel_path = str(args.get("path") or "")
    args_list = args.get("args") or []
    try:
        timeout = int(args.get("timeout", 600))
    except (TypeError, ValueError):
        timeout = 600

    target_path = resolve_in_project_jail(rel_path, project_root)
    if (
        target_path is None
        or not target_path.exists()
        or not target_path.is_file()
    ):
        message = (
            f"Chad tried to run_python_script {rel_path!r} but the file does not exist, "
            "is not a file, or is outside the project jail."
        )
        return "", message

    try:
        proc = subprocess.run(
            ["python3", str(target_path), *[str(a) for a in args_list]],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        tool_result = (
            f"Exit code: {proc.returncode}\n\n"
            f"STDOUT:\n{proc.stdout}\n\n"
            f"STDERR:\n{proc.stderr}"
        )
        message = (
            f"Chad ran run_python_script on {rel_path!r} "
            f"with args {args_list!r} (exit code {proc.returncode})."
        )
        return tool_result, message
    except Exception as e:  # noqa: BLE001
        message = f"Chad failed to run_python_script due to error: {e!r}"
        return "", message


register_tool("run_python_script", _run_python_script)
