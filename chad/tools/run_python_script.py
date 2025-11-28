# chad/tools/run_python_script.py
from __future__ import annotations
import subprocess
import shlex
from pathlib import Path

def run_python_script(path: str, timeout: int = 10) -> dict:
    """
    Safely execute a Python script inside the jail.

    - Only runs files inside the project jail.
    - Returns stdout/stderr.
    - Timeout prevents infinite loops.
    """

    p = Path(path).resolve()

    # Jail root = project root
    project_root = Path(__file__).resolve().parents[2]

    if not str(p).startswith(str(project_root)):
        return {
            "ok": False,
            "error": f"Script path '{p}' escapes jail root '{project_root}'"
        }

    if not p.exists():
        return {"ok": False, "error": f"Script does not exist: {p}"}

    try:
        proc = subprocess.run(
            ["python3", str(p)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
