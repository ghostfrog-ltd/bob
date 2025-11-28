# chad/fs_tools.py
# TODO: This module needs better error handling


from __future__ import annotations

from pathlib import Path


def _detect_comment_prefix(path: Path) -> str:
    """
    Very simple comment-style detector based on file extension.
    Used for the 'prepend_comment' operation.
    """
    ext = path.suffix.lower()
    if ext in {".py", ".sh"}:
        return "# "
    if ext in {".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h"}:
        return "// "
    if ext in {".php"}:
        return "// "
    return "# "


def _resolve_in_project_jail(relative_path: str, project_root: Path) -> Path | None:
    """
    Resolve a relative path against project_root, enforcing the jail.
    Returns a Path or None if the path escapes the jail.
    """
    if not relative_path:
        relative_path = "."
    target = (project_root / relative_path).resolve()
    try:
        target.relative_to(project_root)
    except ValueError:
        return None
    return target
