from __future__ import annotations

"""
helpers/tools_prompt.py

Utilities for turning TOOL_REGISTRY into a human-readable block
for Bob's system prompt.
"""

from typing import Any, Iterable, Tuple

from bob.tools_registry import TOOL_REGISTRY


def _iter_tools() -> Iterable[Tuple[str, Any]]:
    """
    Normalise TOOL_REGISTRY into (name, tool_obj) pairs.

    Supports:
    - dict: {name: tool_obj}
    - iterable: [tool_obj or dict with a 'name' field]
    """
    registry = TOOL_REGISTRY

    # Case 1: dict mapping name -> tool
    if isinstance(registry, dict):
        for name, tool_obj in registry.items():
            yield str(name), tool_obj
        return

    # Case 2: iterable of tool descriptors
    for entry in registry:
        if isinstance(entry, dict):
            name = (
                entry.get("name")
                or entry.get("tool_name")
                or "unnamed_tool"
            )
            tool_obj = entry
        else:
            name = getattr(entry, "name", None) or getattr(entry, "tool_name", None)
            name = name or "unnamed_tool"
            tool_obj = entry
        yield str(name), tool_obj


def describe_tools_for_prompt() -> str:
    """
    Build a human-readable list of tools for Bob's system prompt, based on TOOL_REGISTRY.

    For each tool we try, in order:
    - tool.description attribute
    - dict["description"] / dict["doc"]
    - __doc__ string
    """
    lines: list[str] = []

    for name, tool_obj in _iter_tools():
        desc = getattr(tool_obj, "description", None)

        if not desc and isinstance(tool_obj, dict):
            desc = tool_obj.get("description") or tool_obj.get("doc")

        if not desc:
            desc = getattr(tool_obj, "__doc__", "") or ""

        desc_str = " ".join(str(desc).strip().split())
        if desc_str:
            lines.append(f"- {name}: {desc_str}")
        else:
            lines.append(f"- {name}")

    return "\n".join(lines)
