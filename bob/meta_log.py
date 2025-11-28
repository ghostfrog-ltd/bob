# bob/meta_log.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Mirror paths from bob/meta.py
ROOT_DIR = Path(__file__).resolve().parents[1]  # .../ghostfrog-project-bob
DATA_DIR = ROOT_DIR / "data"
META_DIR = DATA_DIR / "meta"
HISTORY_FILE = META_DIR / "history.jsonl"


def _ensure_dirs() -> None:
    META_DIR.mkdir(parents=True, exist_ok=True)


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
    Append a single run summary to data/meta/history.jsonl.

    Call this once per Bob/Chad task (including self-improvement runs).
    """
    _ensure_dirs()
    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "target": target,                 # e.g. "gf_aab", "self", "other_project"
        "result": result,                 # "success", "fail", "partial"
        "tests": tests,                   # "pass", "fail", "not_run"
        "error_summary": error_summary,
        "human_fix_required": human_fix_required,
    }
    if extra:
        record.update(extra)

    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


import gzip
import shutil
from datetime import datetime, timedelta
import os

# Set rotation parameters
MAX_RECORDS = 1000  # Max records before rotation
ROTATION_DAYS = 7   # Rotate files older than this


def rotate_meta_log(log_file_path):
    """Rotate and compress old meta log files."""
    if not os.path.exists(log_file_path):
        return

    # Rotate based on file size (number of lines)
    with open(log_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    if len(lines) < MAX_RECORDS:
        # No rotation needed
        return

    # Rotate: archive the current log with a timestamp suffix
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    archive_name = f"{log_file_path}.{timestamp}"

    os.rename(log_file_path, archive_name)

    # Create a new empty log file
    open(log_file_path, 'w', encoding='utf-8').close()

    # Optionally gzip the archived file
    with open(archive_name, 'rb') as f_in:
        with gzip.open(f"{archive_name}.gz", 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(archive_name)


def vacuum_meta_log(log_dir):
    """Remove compressed meta log files older than ROTATION_DAYS."""
    cutoff_date = datetime.now() - timedelta(days=ROTATION_DAYS)

    for file_name in os.listdir(log_dir):
        if file_name.endswith('.gz') and file_name.startswith('meta_log'):
            full_path = os.path.join(log_dir, file_name)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(full_path))
            if file_mtime < cutoff_date:
                os.remove(full_path)


# Patch or extend the existing meta_log writing function
# Assuming there's a method called `write_meta_log` or similar

_orig_write_meta_log = None


def patched_write_meta_log(log_file_path, record):
    # Backup original function call
    if _orig_write_meta_log:
        _orig_write_meta_log(log_file_path, record)
    else:
        # Basic append if no original function
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(record + '\n')

    # Try rotation after writing
    try:
        rotate_meta_log(log_file_path)
    except Exception:
        # Fail silently to avoid impact
        pass


def vacuum(log_dir):
    # Public function for vacuuming
    try:
        vacuum_meta_log(log_dir)
    except Exception:
        pass


# Hook into existing meta_log.py interface if possible


# Example: add vacuum as a subcommand callable

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'vacuum':
        log_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
        vacuum(log_dir)
        print(f"Vacuumed old meta_log gz files in {log_dir}")
    else:
        print("Usage: meta_log.py vacuum [log_dir]")


import os
import gzip
import shutil
from datetime import datetime, timedelta

# Configuration parameters for rotation
LOG_ROTATION_DAYS = 7  # retain logs for 7 days
LOG_HISTORY_MAX_RECORDS = 10000  # optional max number of records before rotate

# Path to the meta_log directory - assumed existing attribute or configurable


def rotate_meta_log(log_dir):
    """Rotate meta_log history files older than LOG_ROTATION_DAYS by compressing them and removing very old files."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=LOG_ROTATION_DAYS)

    # Iterate files in log_dir
    for filename in os.listdir(log_dir):
        if not filename.startswith("meta_log_"):
            continue
        full_path = os.path.join(log_dir, filename)

        # Skip non-files
        if not os.path.isfile(full_path):
            continue

        # Parse date from filename suffix - expect meta_log_YYYY-MM-DD.log (optionally .gz)
        try:
            base, ext = os.path.splitext(filename)
            if ext == ".gz":
                base, ext = os.path.splitext(base)
            # base now: meta_log_YYYY-MM-DD
            date_str = base.replace("meta_log_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            # ignore files that don't match the expected pattern
            continue

        if file_date < cutoff and ext != ".gz":
            # Compress the file
            compress_file(full_path)
        elif file_date < cutoff - timedelta(days=LOG_ROTATION_DAYS * 2):
            # Double cutoff: remove very old compressed files
            os.remove(full_path)


def compress_file(filepath):
    """Gzip compress a given file safely by creating a .gz and removing original."""
    gz_path = filepath + ".gz"
    with open(filepath, 'rb') as f_in:
        with gzip.open(gz_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(filepath)


def vacuum(log_dir):
    """Subcommand for vacuuming meta_log: rotates and compresses old logs."""
    rotate_meta_log(log_dir)

# TODO: Integrate calls to vacuum() where appropriate in meta_log write lifecycle.


