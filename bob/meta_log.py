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
