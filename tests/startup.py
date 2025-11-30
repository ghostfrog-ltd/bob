# tests/startup.py
from __future__ import annotations

def run_tests_on_startup() -> bool:
    """
    Run pytest before starting the web app.

    Returns True if tests pass (or pytest isn't installed),
    False if they fail.
    """
    try:
        import pytest
    except ImportError:
        print("[GhostFrog] pytest not installed; skipping tests.")
        return True

    print("[GhostFrog] Running test suite before startup...")
    # Adjust the path "tests" if your tests live somewhere else
    result = pytest.main(["-q", "tests"])

    if result != 0:
        print(f"[GhostFrog] Tests FAILED (exit code {result}); not starting server.")
        return False

    print("[GhostFrog] Tests passed; starting server.")
    return True
