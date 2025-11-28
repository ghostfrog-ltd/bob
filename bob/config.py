from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from openai import OpenAI


@lru_cache(maxsize=1)
def get_openai_client() -> Optional[OpenAI]:
    """
    Shared OpenAI client for Bob.

    Returns None if OPENAI_API_KEY is not set (caller should fall back
    to stub behaviour in that case).
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def get_model_name(default: str = "gpt-4.1-mini") -> str:
    """
    Resolve Bob's model name from env, with a sensible default.
    """
    return os.getenv("BOB_MODEL", default)


# Add configurations for jailed project base directory enforcement
DEFAULT_PROJECT_BASE_DIR = '.'  # default base for jail enforcement

# Add configuration or flag to enable stricter path checks in planner and I/O
ENABLE_STRICT_PATH_JAIL_ENFORCEMENT = True


# Add configuration for jail root path if not already present
# This can be used by planner, text_io, and notes modules to uniformly enforce jail

JAIL_ROOT = '/app/project_root'  # Example path, adjust as per actual project environment


# Adding config flag to enable robust file existence prechecks
ENABLE_FILE_EXISTENCE_PRECHECKS = True

