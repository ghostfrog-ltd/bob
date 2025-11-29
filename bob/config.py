# bob/config.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from openai import OpenAI


@lru_cache(maxsize=1)
def get_openai_client() -> Optional[OpenAI]:
    """
    Return a cached OpenAI client configured with the API key from the environment.

    If OPENAI_API_KEY is missing, return None.
    Callers must handle the None-case (e.g., fall back to local models or stub mode).

    Returns:
        OpenAI | None
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def get_model_name(default: str = "gpt-4.1-mini") -> str:
    """
    Resolve Bob's model name from the environment with a safe fallback.

    Env:
        BOB_MODEL - override model name

    Args:
        default: Model fallback if no env override is provided.

    Returns:
        Name of the model to use.
    """
    return os.getenv("BOB_MODEL", default)


# ---------------------------------------------------------------------------
# Path Jail / Filesystem Safety
# ---------------------------------------------------------------------------

DEFAULT_PROJECT_BASE_DIR: str = "."
"""
Default location used when no explicit jail root is provided.
Used by planner and I/O helpers to interpret relative paths.
"""

ENABLE_STRICT_PATH_JAIL_ENFORCEMENT: bool = True
"""
Global flag enabling jail boundary checks.
If True, any path escaping the jail root should be rejected by Chad.
"""

JAIL_ROOT: str = "/app/project_root"
"""
Absolute base directory for the entire Bob/Chad project jail.

All read/write operations should resolve paths relative to this root.
Tools and helpers should ensure no traversal escapes this boundary.
"""


# ---------------------------------------------------------------------------
# File Handling Behaviour
# ---------------------------------------------------------------------------

ENABLE_FILE_EXISTENCE_PRECHECKS: bool = True
"""
If True, Chad's tools will explicitly check for file existence
before operating on a target path. Helps prevent surprise errors.
"""

FILE_MISSING_BEHAVIOR: str = "raise"
"""
Policy for how tools handle missing target files.

Options:
    - 'raise' : Throw an error (strict, safest)
    - 'warn'  : Log a warning and continue
    - 'ignore': Silently continue
"""


# ---------------------------------------------------------------------------
# Test / Import Controls
# ---------------------------------------------------------------------------

TEST_IMPORT_RETRY_LIMIT: int = 1
"""
Number of times Chad may retry certain imports (e.g., dynamic tool modules)
before giving up. Set higher if tests sometimes race-loading new modules.
"""
