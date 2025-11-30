#!/usr/bin/env python3
# app.py – GhostFrog Bob ↔ Chad message bus + UI (PoC)

from __future__ import annotations

"""
Flask UI + API for GhostFrog Bob/Chad.

You run:

    cd /Volumes/Bob/www/ghostfrog-project-bob
    python3 app.py

UI: http://127.0.0.1:8765/chat
"""

import os
import smtplib  # keep this so tests can monkeypatch app.smtplib
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from bob.meta_log import log_history_record
from bob.schema import BOB_PLAN_SCHEMA  # noqa: F401  (exported for tests/introspection)
from bob.planner import bob_build_plan, bob_refine_codemod_with_files
from bob.chat import bob_simple_chat, bob_answer_with_context
from chad.executor import chad_execute_plan as _chad_execute_plan
from web.chat import create_chat_blueprint

# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

load_dotenv()

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

AI_ROOT = Path(__file__).resolve().parent
DATA_ROOT = AI_ROOT / "data"
QUEUE_DIR = DATA_ROOT / "queue"
SCRATCH_DIR = DATA_ROOT / "scratch"
SEQ_FILE = DATA_ROOT / "seq.txt"
MARKDOWN_NOTES_DIR = DATA_ROOT / "notes"

# UI folder
UI_ROOT = AI_ROOT / "ui"
CHAT_TEMPLATE_PATH = UI_ROOT / "chat_ui.html"

for d in (DATA_ROOT, QUEUE_DIR, SCRATCH_DIR, MARKDOWN_NOTES_DIR, UI_ROOT):
    d.mkdir(parents=True, exist_ok=True)

# Project jail – Bob/Chad only touch files inside here
ENV_PROJECT_JAIL = os.getenv("ENV_PROJECT_JAIL")
if ENV_PROJECT_JAIL:
    PROJECT_ROOT = Path(ENV_PROJECT_JAIL).resolve()
else:
    PROJECT_ROOT = AI_ROOT.resolve()


# ---------------------------------------------------------------------------
# Auto-repair helper
# ---------------------------------------------------------------------------

def _auto_repair_then_retry_async() -> None:
    """
    Fire-and-forget: run `python3 -m bob.meta repair_then_retry` in the
    background so Bob/Chad can self-repair and retry the last failed job.
    """

    def _run() -> None:
        try:
            subprocess.run(
                [sys.executable, "-m", "bob.meta", "repair_then_retry"],
                cwd=str(AI_ROOT),
                check=False,
            )
        except Exception as e:
            print(f"[Bob/Chad] auto repair_then_retry crashed: {e!r}")

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# ID generator: 00001_YYYY-MM-DD
# ---------------------------------------------------------------------------

def next_message_id() -> tuple[str, str, str]:
    """
    Generate a monotonically increasing ID for each message, plus a date-based base name.

    Returns:
        (id_str, date_str, base)
        - id_str: zero-padded sequence, e.g. "00001"
        - date_str: "YYYY-MM-DD"
        - base: f"{id_str}_{date_str}"
    """
    today = date.today().strftime("%Y-%m-%d")

    if SEQ_FILE.exists():
        try:
            current = int(SEQ_FILE.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            current = 0
    else:
        current = 0

    new_val = current + 1
    SEQ_FILE.write_text(str(new_val), encoding="utf-8")

    id_str = f"{new_val:05d}"
    base = f"{id_str}_{today}"
    return id_str, today, base


# ---------------------------------------------------------------------------
# Chad – wrapper around chad/executor.py
# ---------------------------------------------------------------------------

def chad_execute_plan(id_str: str, date_str: str, base: str, plan: dict) -> dict:
    """
    Backwards-compatible wrapper so existing tests that import app.chad_execute_plan
    still work, while delegating the real work to chad.executor.chad_execute_plan.
    """
    return _chad_execute_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        plan=plan,
        project_root=PROJECT_ROOT,
        queue_dir=QUEUE_DIR,
        scratch_dir=SCRATCH_DIR,
        notes_dir=MARKDOWN_NOTES_DIR,
    )


# ---------------------------------------------------------------------------
# Flask app + blueprint registration
# ---------------------------------------------------------------------------

app = Flask(__name__)

chat_bp = create_chat_blueprint(
    chat_template_path=CHAT_TEMPLATE_PATH,
    project_root=PROJECT_ROOT,
    queue_dir=QUEUE_DIR,
    scratch_dir=SCRATCH_DIR,
    next_message_id=next_message_id,
    bob_build_plan=bob_build_plan,
    bob_refine_codemod_with_files=bob_refine_codemod_with_files,
    bob_simple_chat=bob_simple_chat,
    bob_answer_with_context=bob_answer_with_context,
    chad_execute_plan=chad_execute_plan,
    log_history_record=log_history_record,
    auto_repair_fn=_auto_repair_then_retry_async,
)
app.register_blueprint(chat_bp)

# ---------------------------------------------------------------------------
# Run tests before starting server
# ---------------------------------------------------------------------------

try:
    from tests.startup import run_tests_on_startup
except ImportError:  # just in case tests module isn't present
    def run_tests_on_startup() -> bool:  # type: ignore[no-redef]
        return True

if __name__ == "__main__":
    if run_tests_on_startup():
        print("[Bob/Chad] Web UI starting on http://127.0.0.1:8765/chat")
        app.run(host="127.0.0.1", port=8765)
