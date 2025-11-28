# chad/text_io.py
from __future__ import annotations

from pathlib import Path


def _normalize_newlines(text: str) -> str:
    """
    Normalise all line endings to LF ('\\n') so git diffs stay sane.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _safe_read_text(path: Path) -> str:
    """
    Read a text file as UTF-8, tolerating dodgy bytes so we don't crash
    if something is already slightly corrupted.
    """
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        data = f.read()
    return _normalize_newlines(data)


def _contains_suspicious_control_chars(text: str) -> bool:
    """
    Return True if text contains ASCII control characters other than
    newline, carriage-return, or tab.
    """
    for ch in text:
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
            return True
    return False


def _strip_suspicious_control_chars(text: str) -> str:
    """
    Strip vertical-tabs, form-feeds, etc. while keeping newlines and tabs.
    """
    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if code < 32 and ch not in ("\n", "\r", "\t"):
            continue
        cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def _safe_write_text(path: Path, text: str) -> None:
    """
    Write UTF-8 text with LF newlines only.
    """
    if not isinstance(text, str):
        text = str(text)

    text = _normalize_newlines(text)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def safe_read_file(filepath: str) -> str:
    """Safely read the content of a file. Raises FileNotFoundError with
a clear message if the file does not exist."""
    import os
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"The target file '{filepath}' does not exist on disk.")
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


# Add more detailed and robust error handling when reading files
import logging

logger = logging.getLogger(__name__)

_original_read_file = None

def safe_read_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"File not found when trying to read: {filepath}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading file {filepath}: {e}")
        return None

# Patch existing read_file function if present
try:
    import chad.text_io as text_io_mod
    if hasattr(text_io_mod, 'read_file'):
        _original_read_file = text_io_mod.read_file
        text_io_mod.read_file = safe_read_file
except ImportError:
    pass


# Wrap file reading operations to handle missing files gracefully
import os
import logging

def safe_read_text(file_path):
    if not os.path.exists(file_path):
        logging.warning(f"[TextIO] File does not exist when attempting to read: {file_path}")
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

# Possible patch: replace original read_text calls with safe_read_text in Chad where applicable


import os

def safe_read_file(filepath: str) -> str:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found when attempting to read: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def safe_write_file(filepath: str, content: str):
    dir_path = os.path.dirname(filepath)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


import os


def safe_read_file(filepath):
    """Attempt to read a file safely, providing clear error if not found."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Target file does not exist on disk: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def safe_write_file(filepath, content):
    """Write to a file safely, ensuring directory exists."""
    dirpath = os.path.dirname(filepath)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# Existing file operations should be updated in code that uses reading/writing files to use these safe functions where possible, catching FileNotFoundError and handling gracefully.


