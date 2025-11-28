# chad/notes.py
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


from chad.text_io import safe_read_file

def load_note_content(note_path: str) -> str:
    try:
        content = safe_read_file(note_path)
    except FileNotFoundError as e:
        # Log or handle missing note file gracefully
        raise FileNotFoundError(f"Note file missing: {note_path}") from e
    return content


# Improve notes management related to paths to be safer
# Add new utility to sanitize and validate paths within notes
import os

def safe_get_abs_path(base_dir, target_path):
    """Return an absolute path to target_path ensuring it stays within base_dir jail."""
    abs_path = os.path.abspath(os.path.join(base_dir, target_path))
    if not abs_path.startswith(os.path.abspath(base_dir)):
        raise ValueError(f"Path escape detected: {abs_path} is outside base directory {base_dir}")
    return abs_path

# This utility can be used when notes implement or read/write paths, reinforcing jail safety


# Defensive patch: Warn or fix when an attempt is made to schedule 'create_or_overwrite_file'

def safe_schedule_tool(tool_name, *args, **kwargs):
    if tool_name == 'create_or_overwrite_file':
        # Log warning (print in dev) or raise a friendly error
        print("Warning: 'create_or_overwrite_file' is not a valid tool. Using 'create_markdown_note' instead.")
        tool_name = 'create_markdown_note'
    # Original scheduling call here
    return original_schedule_tool(tool_name, *args, **kwargs)

# This requires original_schedule_tool to be defined or imported.

