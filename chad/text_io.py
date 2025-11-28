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
