from __future__ import annotations

from pathlib import Path

# assume PROJECT_ROOT is imported or defined in this module
# from app import PROJECT_ROOT  # or defined above


def resolve_in_project_jail(
    relative_path: str,
    project_root: Path | None = None,
) -> Path | None:
    """
    Resolve a relative path against the project jail.

    If project_root is not provided, fall back to the global PROJECT_ROOT.
    Returns None if the resolved path escapes the jail.
    """
    from app import PROJECT_ROOT as APP_PROJECT_ROOT  # if needed to avoid circulars

    if not project_root:
        project_root = APP_PROJECT_ROOT

    if not relative_path:
        relative_path = "."

    target = (project_root / relative_path).resolve()

    try:
        target.relative_to(project_root)
    except ValueError:
        # Escapes the jail -> reject
        return None

    return target