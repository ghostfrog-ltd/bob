# chad/tools/markdown_notes_tool.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from helpers.text import slugify_for_markdown

from . import register_tool, ToolResult


def _create_markdown_note(
    args: Dict[str, Any],
    project_root: Path,  # unused
    notes_dir: Path,
    scratch_dir: Path,   # unused
) -> ToolResult:
    title = str(args.get("title") or args.get("name") or "").strip()
    content = str(args.get("content") or "")
    slug = slugify_for_markdown(title or "note")
    note_path = notes_dir / f"{slug}.md"

    note_path.write_text(content, encoding="utf-8")
    tool_result = f"Created markdown note '{title or slug}' at notes/{slug}.md."
    message = "Chad created a new markdown note."
    return tool_result, message


def _append_to_markdown_note(
    args: Dict[str, Any],
    project_root: Path,  # unused
    notes_dir: Path,
    scratch_dir: Path,   # unused
) -> ToolResult:
    title = str(args.get("title") or args.get("name") or "").strip()
    content = str(args.get("content") or "")
    slug = slugify_for_markdown(title or "note")
    note_path = notes_dir / f"{slug}.md"

    if note_path.exists():
        with note_path.open("a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                content_to_write = content + "\n"
            else:
                content_to_write = content
            f.write(content_to_write)
        tool_result = (
            f"Appended to markdown note '{title or slug}' at notes/{slug}.md."
        )
        message = "Chad appended to an existing markdown note."
    else:
        note_path.write_text(content, encoding="utf-8")
        tool_result = (
            f"Note '{title or slug}' did not exist; created notes/{slug}.md."
        )
        message = "Chad could not find an existing markdown note, so he created it."

    return tool_result, message


register_tool("create_markdown_note", _create_markdown_note)
register_tool("append_to_markdown_note", _append_to_markdown_note)
