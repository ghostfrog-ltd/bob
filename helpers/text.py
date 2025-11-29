from __future__ import annotations

from pathlib import Path
from datetime import datetime


def normalize_newlines(text: str) -> str:
    """
    Normalize all line endings to Unix-style LF (`\n`).

    This prevents Git diffs from becoming noisy when files contain CRLF or
    mixed newline types. Used by write helpers before committing text to disk.

    Args:
        text: Arbitrary string content, potentially containing CRLF/CR/ mixed endings.

    Returns:
        A string where all line endings are converted to '\n'.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def safe_read_text(target_path: str) -> str:
    """
    Safely read a file for diffing or processing.

    Behaviour:
    - If the file does not exist, return an empty string (treated as a new file).
    - Read using UTF-8 with `errors="replace"` so invalid bytes never crash Chad.
    - If a race condition deletes the file between exists() and open(), return "".

    Args:
        target_path: Filesystem path to read.

    Returns:
        Text content of the file, or an empty string if missing/unreadable.
    """
    path = Path(target_path)

    if not path.exists():
        return ""

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def detect_comment_prefix(path: Path) -> str:
    """
    Guess a comment prefix based on file extension.

    Used by `prepend_comment` tools to avoid corrupting file syntax.

    Args:
        path: Path object whose extension determines comment style.

    Returns:
        A string prefix such as "# " or "// ".
    """
    ext = path.suffix.lower()

    if ext in {".py", ".sh"}:
        return "# "
    if ext in {".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h"}:
        return "// "
    if ext == ".php":
        return "// "

    return "# "


def slugify_for_markdown(title: str) -> str:
    """
    Convert a title into a safe Markdown-compatible slug.

    Behaviour:
    - Lowercase, alphanumeric-only, replacing all other characters with '-'.
    - Collapse multiple dashes.
    - If the title is blank or reduces to nothing, fall back to a timestamp slug.

    Args:
        title: Raw input string, possibly empty or containing symbols.

    Returns:
        A filesystem/markdown-safe slug string, e.g. 'error-log-20250101'.
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


def contains_suspicious_control_chars(text: str) -> bool:
    """
    Detect whether text contains unusual control characters.

    Allowed control characters:
    - newline (\n)
    - carriage return (\r)
    - tab (\t)

    Anything below ASCII 32 that isn't one of the above is considered suspicious.

    Args:
        text: The text to analyse.

    Returns:
        True if suspicious characters are detected, otherwise False.
    """
    for ch in text:
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
            return True
    return False


def strip_suspicious_control_chars(text: str) -> str:
    """
    Remove suspicious control characters from text.

    This cleans data before writing, preventing corruption in diffs, markdown,
    or JSON output.

    Args:
        text: Input string possibly containing bad control characters.

    Returns:
        Cleaned string with only safe characters preserved.
    """
    return "".join(
        ch
        for ch in text
        if not (ord(ch) < 32 and ch not in ("\n", "\r", "\t"))
    )


def safe_write_text(path: Path, text: str) -> None:
    """
    Safely write text to a file with newline normalization.

    Behaviour:
    - Converts non-string input to string.
    - Normalizes line endings to '\n'.
    - Ensures parent directories exist.
    - Writes using UTF-8 with enforced LF newlines.

    Args:
        path: Target path for write operation.
        text: Content to write (any type, will be coerced to string).

    Returns:
        None
    """
    if not isinstance(text, str):
        text = str(text)

    text = normalize_newlines(text)
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
