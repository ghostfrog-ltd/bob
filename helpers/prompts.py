from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict

# AI_ROOT is the project root where app.py lives
AI_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = AI_ROOT / "prompts"

_cache_lock = threading.Lock()
_cache: Dict[str, str] = {}


def _load_raw_prompt(name: str) -> str:
    """
    Load a prompt file from prompts/ by simple name, e.g.:

        "bob_plan_system" -> prompts/bob_plan_system.md
    """
    path = PROMPTS_ROOT / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def get_prompt(name: str, **vars: object) -> str:
    """
    Get a prompt template by name and format it with {{var}} placeholders.

    - Simple string replacement, no heavy templating.
    """
    with _cache_lock:
        text = _cache.get(name)
        if text is None:
            text = _load_raw_prompt(name)
            _cache[name] = text

    for k, v in vars.items():
        v_str = str(v)
        text = text.replace("{{ " + k + " }}", v_str)
        text = text.replace("{{" + k + "}}", v_str)
    return text
