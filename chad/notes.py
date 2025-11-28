from __future__ import annotations

from datetime import datetime


def _slugify_for_markdown(title: str) -> str:
    """
    Crude slugifier for markdown note filenames.
    """
    base = "".join(
        ch.lower() if ch.isalnum() else "-"
        for ch in (title or "").strip()
    ).strip("-")
    if not base:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"note-{timestamp}"
    while "--" in base:
        base = base.replace("--", "-")
    return base
