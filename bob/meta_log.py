# bob/meta_log.py
from __future__ import annotations

import json
import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Paths (mirrored from bob/meta.py)
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]  # .../ghostfrog-project-bob
DATA_DIR = ROOT_DIR / "data"
META_DIR = DATA_DIR / "meta"
HISTORY_FILE = META_DIR / "history.jsonl"

# ---------------------------------------------------------------------------
# Rotation / retention configuration
# ---------------------------------------------------------------------------

# Rotate the active JSONL history once it grows beyond this many records
MAX_HISTORY_RECORDS: int = 1000

# Retain compressed history archives for this many days
HISTORY_RETENTION_DAYS: int = 30


def _ensure_dirs() -> None:
    """Ensure the meta directory exists."""
    META_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# History logging
# ---------------------------------------------------------------------------

def log_history_record(
    *,
    target: str,
    result: str,
    tests: Optional[str] = None,
    error_summary: Optional[str] = None,
    human_fix_required: Optional[bool] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append a single run summary line to data/meta/history.jsonl.

    Each record is written as one JSON document per line and is suitable for
    later streaming / grep / off-line analysis.

    Args:
        target: Logical target of the run, e.g. "gf_aab", "self", "other_project".
        result: High-level outcome, e.g. "success", "fail", "partial".
        tests: Test outcome summary, e.g. "pass", "fail", "not_run".
        error_summary: Short description of any error encountered (if any).
        human_fix_required: Whether human intervention is likely needed.
        extra: Optional dict of additional structured fields to merge in.
    """
    _ensure_dirs()

    record: Dict[str, Any] = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "target": target,
        "result": result,
        "tests": tests,
        "error_summary": error_summary,
        "human_fix_required": human_fix_required,
    }
    if extra:
        record.update(extra)

    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")

    _rotate_history_if_needed()


# ---------------------------------------------------------------------------
# Rotation / vacuum helpers
# ---------------------------------------------------------------------------

def _rotate_history_if_needed() -> None:
    """
    Rotate history.jsonl when it grows beyond MAX_HISTORY_RECORDS.

    Rotation strategy:
      - Count lines in HISTORY_FILE.
      - If above threshold, rename to a timestamped archive and gzip it.
      - Create a new empty HISTORY_FILE.
    """
    if not HISTORY_FILE.exists():
        return

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
    except OSError:
        # If we can't read for some reason, skip rotation rather than crash.
        return

    if line_count < MAX_HISTORY_RECORDS:
        return

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    archive_path = META_DIR / f"history_{timestamp}.jsonl"

    try:
        HISTORY_FILE.rename(archive_path)
    except OSError:
        # If rename fails, don't block logging.
        return

    # Create a fresh empty history file
    HISTORY_FILE.touch()

    # Compress archive to .gz and remove original
    gz_path = archive_path.with_suffix(archive_path.suffix + ".gz")
    try:
        with archive_path.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        archive_path.unlink(missing_ok=True)
    except OSError:
        # If compression fails, leave the uncompressed archive in place.
        pass


def vacuum(log_dir: Optional[str | Path] = None) -> None:
    """
    Vacuum old compressed history archives.

    Removes *.gz files older than HISTORY_RETENTION_DAYS from the given
    directory (defaults to META_DIR).

    Args:
        log_dir: Directory containing compressed history archives.
    """
    base_dir = Path(log_dir) if log_dir is not None else META_DIR
    if not base_dir.exists():
        return

    cutoff = datetime.utcnow() - timedelta(days=HISTORY_RETENTION_DAYS)

    for entry in base_dir.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.startswith("history_") or not entry.name.endswith(".gz"):
            continue

        try:
            mtime = datetime.utcfromtimestamp(entry.stat().st_mtime)
        except OSError:
            continue

        if mtime < cutoff:
            try:
                entry.unlink()
            except OSError:
                # Best-effort cleanup; don't crash.
                pass


# ---------------------------------------------------------------------------
# CLI entrypoint (optional)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "vacuum":
        dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
        vacuum(dir_arg)
        print(f"Vacuumed old history archives in {dir_arg or META_DIR}")
    else:
        print("Usage: meta_log.py vacuum [log_dir]")
