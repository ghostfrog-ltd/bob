# chad/tools/run_python_script.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


# Adjust this the same way you do in your other tools
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # /.../ghostfrog-agentic-alert-bot-bob


def run_python_script(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool: run_python_script

    Args:
      path: relative path to a Python script inside the project
      args: optional list of string arguments

    Returns:
      {ok, returncode, stdout, stderr, script, argv}
    """
    rel_path = args.get("path")
    if not rel_path:
        return {"ok": False, "error": "missing 'path' arg"}

    extra_args = args.get("args") or []

    script_path = (PROJECT_ROOT / rel_path).resolve()

    # Safety: keep inside the jail
    try:
        script_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return {"ok": False, "error": "script outside project root"}

    if not script_path.is_file():
        return {"ok": False, "error": f"script not found: {rel_path}"}

    proc = subprocess.run(
        [sys.executable, str(script_path), *extra_args],
        capture_output=True,
        text=True,
    )

    return {
        "ok": proc.returncode == 0,
        "script": rel_path,
        "argv": extra_args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
