# chad/tools/list_files_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple, List

from helpers.jail import resolve_in_project_jail

from . import register_tool, ToolResult


def _run_list_files(
    args: Dict[str, Any],
    project_root: Path,
    notes_dir: Path,    # unused
    scratch_dir: Path,  # unused
) -> ToolResult:
    rel_path = str(args.get("path") or ".")
    recursive = bool(args.get("recursive", False))
    try:
        max_entries = int(args.get("max_entries", 200))
    except (TypeError, ValueError):
        max_entries = 200

    base_path = resolve_in_project_jail(rel_path, project_root)
    if base_path is None or not base_path.exists():
        message = (
            f"Chad tried to list_files at {rel_path!r} but the path was invalid "
            "or outside the project jail."
        )
        return "", message

    entries: List[Dict[str, Any]] = []
    count = 0

    if recursive and base_path.is_dir():
        for path in base_path.rglob("*"):
            if count >= max_entries:
                break
            try:
                rel = str(path.relative_to(project_root))
            except ValueError:
                continue
            if path.is_dir():
                entries.append({"path": rel, "type": "dir", "size": None})
            else:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                entries.append({"path": rel, "type": "file", "size": size})
            count += 1
    elif base_path.is_dir():
        for path in sorted(base_path.iterdir()):
            if count >= max_entries:
                break
            try:
                rel = str(path.relative_to(project_root))
            except ValueError:
                continue
            if path.is_dir():
                entries.append({"path": rel, "type": "dir", "size": None})
            else:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                entries.append({"path": rel, "type": "file", "size": size})
            count += 1
    else:
        try:
            rel = str(base_path.relative_to(project_root))
        except ValueError:
            rel = base_path.name
        try:
            size = base_path.stat().st_size
        except OSError:
            size = None
        entries.append({"path": rel, "type": "file", "size": size})

    if not entries:
        message = f"Chad found no entries under {rel_path!r}."
        tool_result = "No files or directories found."
        return tool_result, message

    lines = ["Path / Type / Size(bytes):"]
    for e in entries:
        if e["type"] == "dir":
            size_str = "dir"
        else:
            size_str = str(e["size"]) if e["size"] is not None else "?"
        lines.append(f"- {e['path']}  [{e['type']}]  {size_str}")

    tool_result = "\n".join(lines)
    message = f"Chad listed up to {len(entries)} entries under {rel_path!r}."
    return tool_result, message


register_tool("list_files", _run_list_files)
