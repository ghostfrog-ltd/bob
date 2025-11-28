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


import os

def safe_read_note_file(filepath):
    """Safely read the note file content if exists, else log and return None."""
    if not os.path.exists(filepath):
        from bob.meta import log_warning
        log_warning(f"Note file does not exist on disk: {filepath}")
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


# Patch note addition to check file existence before writing notes
from pathlib import Path

def safe_write_note(note, filepath):
    try:
        if not Path(filepath).parent.exists():
            # Log and create parent directory if missing
            import logging
            logging.warning(f"Parent directory for note {filepath} does not exist. Creating it.")
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'a') as f:
            f.write(note + '\n')
    except Exception as e:
        import logging
        logging.error(f"Failed to write note to {filepath}: {e}")

# Monkey patch existing add_note function if present
if hasattr(globals(), 'add_note') and callable(globals()['add_note']):
    original_add_note = globals()['add_note']
    def add_note_safe(note, filepath):
        safe_write_note(note, filepath)
    globals()['add_note'] = add_note_safe

