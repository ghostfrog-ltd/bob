#!/usr/bin/env python3
# app.py – GhostFrog Bob ↔ Chad message bus + UI (PoC)

from __future__ import annotations

"""
Flask UI + API for GhostFrog Bob/Chad.

- Serves the dark-mode chat UI at /chat (from ui/chat_ui.html)
- Exposes POST /api/chat:
    * writes the user's message into /data/queue/*.user.txt
    * asks Bob (OpenAI) to build a plan
    * Chad executes the plan (tools / analysis / codemod)
    * returns a summary + snippets back to the browser

You run:

    cd /Volumes/Bob/www/ghostfrog-project-bob
    python3 app.py

UI: http://127.0.0.1:8765/chat
"""

import json
import os
import smtplib
import mimetypes
from email.message import EmailMessage
from datetime import datetime, date, timezone
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string
from dotenv import load_dotenv
from openai import OpenAI

from bob.meta_log import log_history_record

import subprocess
import sys
import threading

# ---------------------------------------------------------------------------
# Env + OpenAI client
# ---------------------------------------------------------------------------

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
BOB_MODEL = os.getenv("BOB_MODEL", "gpt-4.1-mini")

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


def _auto_repair_then_retry_async() -> None:
    """
    Fire-and-forget: run `python3 -m bob.meta repair_then_retry` in the
    background so Bob/Chad can self-repair and retry the last failed job.

    This is deliberately best-effort: any errors are printed but never
    break the HTTP request.
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
# Bob plan schema (for reference)
# ---------------------------------------------------------------------------

BOB_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {
            "type": "string",
            "enum": ["codemod", "analysis", "tool", "chat"],
        },
        "summary": {"type": "string"},
        "analysis_file": {"type": "string", "default": ""},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": [
                            "prepend_comment",
                            "create_or_overwrite_file",
                            "append_to_bottom",
                        ],
                    },
                    "content": {"type": "string"},
                },
                "required": ["file", "operation", "content"],
                "additionalProperties": False,
            },
        },
        "tool": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": [
                        "get_current_datetime",
                        "list_files",
                        "read_file",
                        "create_markdown_note",
                        "append_to_markdown_note",
                        "send_email",
                    ],
                },
                "args": {
                    "type": "object",
                    "additionalProperties": True,
                    "default": {},
                },
            },
            "default": {},
        },
    },
    "required": ["task_type", "summary", "analysis_file", "edits"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# ID generator: 00001_YYYY-MM-DD
# ---------------------------------------------------------------------------


def next_message_id() -> tuple[str, str, str]:
    """
    Returns (id_str, date_str, base_name) like:
      ("00001", "2025-11-23", "00001_2025-11-23")
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
# Bob – planning layer
# ---------------------------------------------------------------------------


def bob_build_plan(
        id_str: str,
        date_str: str,
        base: str,
        user_text: str,
        tools_enabled: bool = True,
) -> dict:
    """
    Bob builds a structured plan for Chad.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        plan: dict = {
            "id": id_str,
            "date": date_str,
            "created_at": now,
            "actor": "bob",
            "kind": "plan",
            "raw_user_text": user_text,
            "task": {
                "type": "chat",
                "summary": f"(STUB – no OPENAI_API_KEY) Handle user request: {user_text}",
                "analysis_file": "",
                "edits": [],
                "tool": {},
            },
        }
        (QUEUE_DIR / f"{base}.plan.json").write_text(
            json.dumps(plan, indent=2), encoding="utf-8"
        )
        return plan

    if tools_enabled:
        tool_mode_text = (
            "Tools ARE ENABLED for this request. You should choose 'tool' whenever "
            "the user is asking you to interact with the live project/filesystem, "
            "write notes, or send email — even if they do NOT mention tool names.\n"
        )
    else:
        tool_mode_text = (
            "Tools ARE DISABLED for this request. You MUST NOT choose task_type "
            "'tool', and you MUST leave the 'tool' object empty.\n"
        )

    system_prompt = (
        "You are Bob, a senior reasoning model orchestrating a local coder called Chad.\n"
        "The user is working on a Python / GhostFrog project.\n\n"
        f"{tool_mode_text}"
        "IMPORTANT EMAIL RULE:\n"
        "- When the user asks you to 'email' something, you MUST choose task_type='tool'\n"
        "  and set tool.name='send_email'. Do NOT leave task_type as 'chat'.\n"
        "  The recipient address is always taken from SMTP_TO/SMTP_TEST_TO in the\n"
        "  environment; any 'to' you put in args will be ignored by Chad.\n\n"
        "Decide between 'chat', 'analysis', 'tool', and 'codemod' as follows:\n"
        "- Use 'tool' for actions involving filesystem/email/notes/date queries.\n"
        "- Use 'analysis' to review a specific file without modifying it.\n"
        "- Use 'codemod' to modify project files.\n"
        "- Use 'chat' for pure Q&A.\n\n"
        "Your output MUST be a JSON object matching this schema:\n"
        f"{json.dumps(BOB_PLAN_SCHEMA, indent=2)}\n"
        "Do not add any extra keys or surrounding text."
    )

    try:
        resp = openai_client.responses.create(
            model=BOB_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            text={"format": {"type": "json_object"}},
        )

        raw = (resp.output_text or "").strip()
        first = raw.find("{")
        last = raw.rfind("}")
        if first != -1 and last != -1:
            raw = raw[first: last + 1]

        body = json.loads(raw)

        task_type = body.get("task_type", "analysis")
        summary = body.get("summary", "").strip() or user_text
        edits = body.get("edits") or []
        analysis_file = body.get("analysis_file") or ""
        tool_obj = body.get("tool") or {}

    except Exception as e:  # pragma: no cover - safety net
        task_type = "analysis"
        summary = f"(STUB – OpenAI error: {e!r}) Handle user request: {user_text}"
        edits = []
        analysis_file = ""
        tool_obj = {}

    plan: dict = {
        "id": id_str,
        "date": date_str,
        "created_at": now,
        "actor": "bob",
        "kind": "plan",
        "raw_user_text": user_text,
        "task": {
            "type": task_type,
            "analysis_file": analysis_file,
            "summary": summary,
            "edits": edits,
            "tool": tool_obj,
        },
    }

    (QUEUE_DIR / f"{base}.plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8"
    )
    return plan


def bob_refine_codemod_with_files(
        user_text: str,
        base_task: dict,
        file_contexts: dict[str, str],
) -> dict:
    """
    Second-pass planner for codemods: refine plan given real file contents.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not file_contexts:
        return base_task

    files_blob_lines: list[str] = []
    for rel_path, contents in file_contexts.items():
        files_blob_lines.append(
            f"===== FILE: {rel_path} =====\n{contents}\n===== END FILE =====\n"
        )
    files_blob = "\n".join(files_blob_lines)

    refine_prompt = (
        "You are Bob, refining your previous codemod plan now that you have the "
        "actual contents of the files from disk.\n\n"
        "You MUST keep task_type='codemod' and produce minimal edits.\n"
        "Do NOT reformat or reorder code; think like a tiny diff.\n"
        f"{json.dumps(BOB_PLAN_SCHEMA, indent=2)}\n"
        "Return ONLY a JSON object."
    )

    try:
        resp = openai_client.responses.create(
            model=BOB_MODEL,
            input=[
                {"role": "system", "content": refine_prompt},
                {
                    "role": "user",
                    "content": (
                        f"User request:\n{user_text}\n\n"
                        "Here are the current file contents you may edit:\n\n"
                        f"{files_blob}"
                    ),
                },
            ],
            text={"format": {"type": "json_object"}},
        )

        raw = (resp.output_text or "").strip()
        first = raw.find("{")
        last = raw.rfind("}")
        if first != -1 and last != -1:
            raw = raw[first: last + 1]

        body = json.loads(raw)

        summary = body.get("summary", base_task.get("summary", "")).strip()
        edits = body.get("edits") or []

        return {
            "type": "codemod",
            "summary": summary or base_task.get("summary", ""),
            "analysis_file": "",
            "edits": edits,
            "tool": {},
        }

    except Exception as e:  # pragma: no cover - safety net
        fallback = dict(base_task)
        fallback.setdefault(
            "summary",
            f"{base_task.get('summary', '')} (codemod refinement failed: {e!r})",
        )
        return fallback


def bob_simple_chat(user_text: str) -> str:
    """
    Simple Q&A mode for Bob when no file / tools are involved.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "You asked: {!r}. I can't call OpenAI because OPENAI_API_KEY is "
            "not configured, but normally I'd answer this directly here."
        ).format(user_text)

    base_prompt = (
        "You are Bob, a helpful AI assistant for a developer working on the "
        "GhostFrog project.\n"
        "Answer directly and concisely; no JSON, no tools."
    )

    try:
        resp = openai_client.responses.create(
            model=BOB_MODEL,
            input=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or "I couldn't generate a detailed answer."
    except Exception as e:  # pragma: no cover - safety net
        return f"I tried to answer but hit an OpenAI error: {e!r}"


def bob_answer_with_context(user_text: str, plan: dict, snippet: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "I’d like to review the file, but there is no OPENAI_API_KEY configured."

    if not snippet:
        base_prompt = (
            "The user asked you about code, but Chad could not provide the file "
            "contents. Answer in general terms."
        )
    else:
        base_prompt = (
            "You are Bob, reviewing code that Chad read from disk.\n"
            "Give a friendly, practical review: explain what it does and suggest "
            "concrete improvements."
        )

    try:
        resp = openai_client.responses.create(
            model=BOB_MODEL,
            input=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": f"User request:\n{user_text}"},
                {"role": "user", "content": f"File contents snippet:\n\n{snippet}"},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or "I looked at the file but couldn't generate a detailed review."
    except Exception as e:  # pragma: no cover - safety net
        return f"I tried to review the file but hit an OpenAI error: {e!r}"


# ---------------------------------------------------------------------------
# Chad – executor layer (tools, analysis, codemod)
# ---------------------------------------------------------------------------


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


from pathlib import Path

def _safe_read_text(target_path: str) -> str:
    """
    Safely read a file for diffing.

    - If the file does not exist, return an empty string instead of raising.
      This lets Chad treat it as a brand-new file.
    - Always read as UTF-8 with replacement, so weird bytes don't crash us.
    """
    path = Path(target_path)

    # New file: treat as empty original.
    if not path.exists():
        return ""

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except FileNotFoundError:
        # Race condition / just deleted: also treat as empty.
        return ""


def _contains_suspicious_control_chars(text: str) -> bool:
    for ch in text:
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
            return True
    return False


def _strip_suspicious_control_chars(text: str) -> str:
    return "".join(
        ch
        for ch in text
        if not (ord(ch) < 32 and ch not in ("\n", "\r", "\t"))
    )


def _safe_write_text(path: Path, text: str) -> None:
    if not isinstance(text, str):
        text = str(text)
    text = _normalize_newlines(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _detect_comment_prefix(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".py", ".sh"}:
        return "# "
    if ext in {".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h", ".php"}:
        return "// "
    return "# "


def _resolve_in_project_jail(relative_path: str) -> Path | None:
    if not relative_path:
        relative_path = "."
    target = (PROJECT_ROOT / relative_path).resolve()
    try:
        target.relative_to(PROJECT_ROOT)
    except ValueError:
        return None
    return target


def _slugify_for_markdown(title: str) -> str:
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


def chad_execute_plan(id_str: str, date_str: str, base: str, plan: dict) -> dict:
    """
    Execute Bob's plan.

    - For task.type == 'tool' → run a local tool.
    - For 'analysis' → read file snippet for Bob.
    - For 'codemod' → apply edits inside PROJECT_ROOT.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    task = plan.get("task") or {}
    task_type = task.get("type", "analysis")
    edits = task.get("edits") or []
    tool_obj = task.get("tool") or {}

    touched: list[str] = []

    # If Bob set a tool but forgot task_type='tool', treat it as tool.
    if tool_obj and task_type != "tool":
        task_type = "tool"

    # ------------------------------------------------------------------
    # TOOL branch
    # ------------------------------------------------------------------
    if task_type == "tool":
        tool_name = tool_obj.get("name") or ""
        tool_args = tool_obj.get("args") or {}
        tool_result = ""
        message = ""

        if tool_name == "get_current_datetime":
            now_local = datetime.now().astimezone()
            dt_str = now_local.strftime("%A, %d %B %Y, %H:%M:%S %Z (%z)")
            tool_result = f"Local system date and time: {dt_str}"
            message = "Chad ran tool 'get_current_datetime' using the system clock."

        elif tool_name == "list_files":
            rel_path = str(tool_args.get("path") or ".")
            recursive = bool(tool_args.get("recursive", False))
            try:
                max_entries = int(tool_args.get("max_entries", 200))
            except (TypeError, ValueError):
                max_entries = 200

            base_path = _resolve_in_project_jail(rel_path)
            if base_path is None or not base_path.exists():
                message = (
                    f"Chad tried to list_files at {rel_path!r} but the path was invalid "
                    "or outside the project jail."
                )
                tool_result = ""
            else:
                entries = []
                count = 0

                if recursive and base_path.is_dir():
                    for path in base_path.rglob("*"):
                        if count >= max_entries:
                            break
                        try:
                            rel = str(path.relative_to(PROJECT_ROOT))
                        except ValueError:
                            continue
                        if path.is_dir():
                            entries.append({"path": rel, "type": "dir", "size": None})
                        else:
                            try:
                                size = path.stat().st_size
                            except OSError:
                                size = None
                            entries.append({"path": rel, "type": "file", "size": size})
                        count += 1
                elif base_path.is_dir():
                    for path in sorted(base_path.iterdir()):
                        if count >= max_entries:
                            break
                        try:
                            rel = str(path.relative_to(PROJECT_ROOT))
                        except ValueError:
                            continue
                        if path.is_dir():
                            entries.append({"path": rel, "type": "dir", "size": None})
                        else:
                            try:
                                size = path.stat().st_size
                            except OSError:
                                size = None
                            entries.append({"path": rel, "type": "file", "size": size})
                        count += 1
                else:
                    try:
                        rel = str(base_path.relative_to(PROJECT_ROOT))
                    except ValueError:
                        rel = base_path.name
                    try:
                        size = base_path.stat().st_size
                    except OSError:
                        size = None
                    entries.append({"path": rel, "type": "file", "size": size})

                if entries:
                    lines = ["Path / Type / Size(bytes):"]
                    for e in entries:
                        size_str = (
                            "dir"
                            if e["type"] == "dir"
                            else (str(e["size"]) if e["size"] is not None else "?")
                        )
                        lines.append(f"- {e['path']}  [{e['type']}]  {size_str}")
                    tool_result = "\n".join(lines)
                    message = (
                        f"Chad listed up to {len(entries)} entries under {rel_path!r}."
                    )
                else:
                    message = f"Chad found no entries under {rel_path!r}."
                    tool_result = "No files or directories found."

        elif tool_name == "read_file":
            rel_path = str(
                tool_args.get("path")
                or tool_args.get("file")
                or ""
            )
            try:
                max_chars = int(tool_args.get("max_chars", 16000))
            except (TypeError, ValueError):
                max_chars = 16000

            target_path = _resolve_in_project_jail(rel_path)
            if target_path is None or not target_path.exists() or not target_path.is_file():
                message = (
                    f"Chad tried to read_file {rel_path!r} but it does not exist, "
                    "is not a file, or is outside the project jail."
                )
                tool_result = ""
            else:
                try:
                    raw = target_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    message = (
                        f"Chad tried to read_file {rel_path!r} but it is not UTF-8 text."
                    )
                    tool_result = ""
                else:
                    if len(raw) > max_chars:
                        tool_result = raw[:max_chars] + "\n\n... (truncated)"
                    else:
                        tool_result = raw
                    message = f"Chad read_file {rel_path!r} (up to {max_chars} chars)."

        elif tool_name in {"create_markdown_note", "append_to_markdown_note"}:
            title = str(tool_args.get("title") or tool_args.get("name") or "").strip()
            content = str(tool_args.get("content") or "")
            slug = _slugify_for_markdown(title or "note")
            note_path = MARKDOWN_NOTES_DIR / f"{slug}.md"

            if tool_name == "create_markdown_note":
                note_path.write_text(content, encoding="utf-8")
                tool_result = (
                    f"Created markdown note '{title or slug}' at notes/{slug}.md."
                )
                message = "Chad created a new markdown note."
            else:
                if note_path.exists():
                    with note_path.open("a", encoding="utf-8") as f:
                        if not content.endswith("\n"):
                            content_to_write = content + "\n"
                        else:
                            content_to_write = content
                        f.write(content_to_write)
                    tool_result = (
                        f"Appended to markdown note '{title or slug}' at notes/{slug}.md."
                    )
                    message = "Chad appended to an existing markdown note."
                else:
                    note_path.write_text(content, encoding="utf-8")
                    tool_result = (
                        f"Note '{title or slug}' did not exist; created notes/{slug}.md."
                    )
                    message = (
                        "Chad could not find an existing markdown note, so he created it."
                    )

        elif tool_name == "send_email":
            # FORCE TO ENV – ignore any 'to' passed in tool_args when env vars exist
            to_addr = (
                    os.getenv("SMTP_TO") or os.getenv("SMTP_TEST_TO") or ""
            ).strip()

            subject = str(tool_args.get("subject") or "").strip()
            body = str(tool_args.get("body") or "")

            attachments_in_args = "attachments" in tool_args
            attachments = tool_args.get("attachments")
            if attachments is None:
                attachments = []

            auto_note = False
            note_path = None
            note_rel_display = None

            if not attachments and not attachments_in_args:
                latest = None
                latest_mtime = None
                for p in MARKDOWN_NOTES_DIR.glob("*.md"):
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    if latest is None or mtime > latest_mtime:
                        latest = p
                        latest_mtime = mtime

                if latest is not None:
                    auto_note = True
                    note_path = latest
                    note_rel_display = f"notes/{latest.name}"
                    try:
                        attachment_rel = str(latest.relative_to(PROJECT_ROOT))
                    except ValueError:
                        attachment_rel = str(latest)
                    attachments = [attachment_rel]

                    if not subject:
                        subject = f"[GhostFrog] {latest.name}"

            smtp_host = os.getenv("SMTP_HOST")
            security = (os.getenv("SMTP_SECURITY") or "starttls").lower()
            port_env = os.getenv("SMTP_PORT")
            if port_env:
                smtp_port = int(port_env)
            else:
                smtp_port = 465 if security == "ssl" else 587

            smtp_user = os.getenv("SMTP_USERNAME")
            smtp_password = os.getenv("SMTP_PASSWORD")
            from_addr = os.getenv("SMTP_FROM") or smtp_user

            if not to_addr:
                message = (
                    "Chad was asked to send_email, but no SMTP_TO / SMTP_TEST_TO "
                    "address is configured in the environment."
                )
                tool_result = ""
            elif not smtp_host or not from_addr:
                message = (
                    "Chad was asked to send_email, but SMTP settings are incomplete "
                    "(need at least SMTP_HOST and SMTP_FROM or SMTP_USERNAME)."
                )
                tool_result = ""
            else:
                try:
                    if security == "ssl":
                        smtp_cls = smtplib.SMTP_SSL
                    else:
                        smtp_cls = smtplib.SMTP

                    with smtp_cls(smtp_host, smtp_port, timeout=30) as server:
                        if security == "starttls":
                            server.starttls()
                        if smtp_user and smtp_password:
                            server.login(smtp_user, smtp_password)

                        msg = EmailMessage()
                        msg["From"] = from_addr
                        msg["To"] = to_addr
                        msg["Subject"] = subject or "(no subject)"
                        msg.set_content(body or "")

                        for rel in attachments:
                            rel_str = str(rel)
                            attach_path = _resolve_in_project_jail(rel_str)
                            if attach_path is None or not attach_path.exists():
                                continue
                            mime_type, _ = mimetypes.guess_type(str(attach_path))
                            if mime_type:
                                maintype, subtype = mime_type.split("/", 1)
                            else:
                                maintype, subtype = "application", "octet-stream"
                            with attach_path.open("rb") as f:
                                data = f.read()
                            msg.add_attachment(
                                data,
                                maintype=maintype,
                                subtype=subtype,
                                filename=attach_path.name,
                            )

                        server.send_message(msg)

                    if auto_note and note_path is not None:
                        try:
                            raw = note_path.read_text(encoding="utf-8")
                        except Exception:
                            preview_body = "(could not read note content)"
                        else:
                            if len(raw) > 16000:
                                preview_body = raw[:16000] + "\n\n... (truncated)"
                            else:
                                preview_body = raw

                        display_name = note_rel_display or note_path.name
                        tool_result = (
                            f"📎 Attached file preview ({display_name}):\n"
                            f"{preview_body}"
                        )
                    else:
                        tool_result = (
                            f"Email sent to {to_addr} with subject: "
                            f"{subject or '(no subject)'}"
                        )

                    message = (
                        f"Chad sent an email to '{to_addr}' with subject {subject!r}."
                    )
                except Exception as e:
                    message = f"Chad failed to send_email due to error: {e!r}"
                    tool_result = ""

        else:
            message = (
                f"Chad was asked to run an unknown tool: {tool_name!r}. "
                "No tool was executed."
            )
            tool_result = ""

        scratch_file = SCRATCH_DIR / f"{base}.txt"
        scratch_file.write_text(
            "GhostFrog Chad tool execution\n"
            f"ID: {base}\n"
            f"Time: {now}\n"
            f"Tool name: {tool_name or '(none)'}\n"
            f"Tool args: {tool_args}\n"
            f"Tool result:\n{tool_result or '(no result)'}\n",
            encoding="utf-8",
        )

        exec_report = {
            "id": id_str,
            "date": date_str,
            "created_at": now,
            "actor": "chad",
            "kind": "exec_result",
            "status": "success",
            "touched_files": [],
            "analysis_file": None,
            "analysis_snippet": "",
            "tool_name": tool_name,
            "tool_result": tool_result,
            "message": message,
        }
        exec_path = QUEUE_DIR / f"{base}.exec.json"
        exec_path.write_text(json.dumps(exec_report, indent=2), encoding="utf-8")
        return exec_report

    # ------------------------------------------------------------------
    # ANALYSIS branch
    # ------------------------------------------------------------------
    if task_type != "codemod":
        analysis_file = task.get("analysis_file") or ""
        analysis_snippet = ""
        target_rel = None

        if analysis_file:
            target_path = (PROJECT_ROOT / analysis_file).resolve()
            try:
                target_path.relative_to(PROJECT_ROOT)
            except ValueError:
                target_path = None

            if target_path is not None and target_path.exists():
                raw = target_path.read_text(encoding="utf-8")
                analysis_snippet = raw[:16000]
                target_rel = str(target_path.relative_to(PROJECT_ROOT))

        scratch_file = SCRATCH_DIR / f"{base}.txt"
        scratch_file.write_text(
            "GhostFrog Chad analysis execution\n"
            f"ID: {base}\n"
            f"Time: {now}\n"
            f"Analysis file: {target_rel or '(none)'}\n",
            encoding="utf-8",
        )

        exec_report = {
            "id": id_str,
            "date": date_str,
            "created_at": now,
            "actor": "chad",
            "kind": "exec_result",
            "status": "success",
            "touched_files": [],
            "analysis_file": target_rel,
            "analysis_snippet": analysis_snippet,
            "message": (
                f"Chad fetched {target_rel} for analysis."
                if target_rel
                else "Chad performed analysis-only; no file was read."
            ),
        }
        exec_path = QUEUE_DIR / f"{base}.exec.json"
        exec_path.write_text(json.dumps(exec_report, indent=2), encoding="utf-8")
        return exec_report

    # ------------------------------------------------------------------
    # CODEMOD branch
    # ------------------------------------------------------------------
    edit_logs: list[dict] = []

    for edit in edits:
        file_rel = edit.get("file")
        op = edit.get("operation")
        content = edit.get("content", "")

        if not file_rel or not op:
            edit_logs.append(
                {
                    "file": file_rel or "(none)",
                    "operation": op or "(none)",
                    "reason": "missing file or operation in edit",
                }
            )
            continue

        target_path = (PROJECT_ROOT / file_rel).resolve()
        try:
            target_path.relative_to(PROJECT_ROOT)
        except ValueError:
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "target path escapes project jail",
                }
            )
            continue

        exists = target_path.exists()

        # ----------------------------------------------------
        # Auto-create behaviour for some operations
        # ----------------------------------------------------
        if not exists:
            if op == "create_or_overwrite_file":
                # Allowed: this op is explicitly for creating/replacing files.
                pass
            elif op in {"prepend_comment", "append_to_bottom"}:
                # For these, we allow Bob to "grow" new files:
                # create an empty file first, then apply the op below.
                target_path.parent.mkdir(parents=True, exist_ok=True)
                _safe_write_text(target_path, "")
                exists = True
            else:
                # For all other ops, missing files are still an error.
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "target file does not exist on disk",
                    }
                )
                continue

        exists = target_path.exists()

        # For most operations, we still require the file to exist.
        # But for create_or_overwrite_file we ALLOW creating a new file
        # as long as it is inside the project jail.
        if op != "create_or_overwrite_file" and not exists:
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "target file does not exist on disk",
                }
            )
            continue

        original = _safe_read_text(target_path)

        if op == "create_or_overwrite_file":
            new_text = _normalize_newlines(content)
            if _contains_suspicious_control_chars(new_text):
                new_text = _strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "new content contained suspicious control characters which were stripped",
                    }
                )

            # Drop Bob's meta-lines
            if target_path.suffix.lower() == ".py":
                lines = new_text.split("\n")
                filtered_lines = [
                    line
                    for line in lines
                    if "rest of code unchanged" not in line
                ]
                new_text = "\n".join(filtered_lines)

                # Preserve Unicode lines (e.g. £, emojis) if Bob normalised them away
                old_lines = original.split("\n")
                new_lines = new_text.split("\n")
                limit = min(len(old_lines), len(new_lines))
                for i in range(limit):
                    old_line = old_lines[i]
                    new_line = new_lines[i]
                    had_unicode = any(ord(ch) > 127 for ch in old_line)
                    has_unicode_now = any(ord(ch) > 127 for ch in new_line)
                    if "£" in old_line and "£" not in new_line:
                        new_lines[i] = old_line
                        continue
                    if had_unicode and not has_unicode_now:
                        new_lines[i] = old_line
                new_text = "\n".join(new_lines)

            if _normalize_newlines(original) == new_text:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "new content is identical to existing file",
                    }
                )
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(PROJECT_ROOT)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "file overwritten with new content",
                }
            )

        elif op == "append_to_bottom":
            new_text_raw = original.rstrip() + "\n\n" + content + "\n"
            new_text = _normalize_newlines(new_text_raw)
            if _contains_suspicious_control_chars(new_text):
                new_text = _strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "resulting content contained suspicious control characters which were stripped",
                    }
                )

            if _normalize_newlines(original) == new_text:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "append produced no effective change",
                    }
                )
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(PROJECT_ROOT)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "content appended to bottom of file",
                }
            )

        elif op == "prepend_comment":
            if target_path.suffix.lower() == ".py":
                content_stripped = content.lstrip()
                if content_stripped.startswith('"""') or content_stripped.startswith(
                        "'''"
                ):
                    lines = original.splitlines()
                    if lines and lines[0].startswith("#!"):
                        new_text_raw = (
                                lines[0]
                                + "\n\n"
                                + content
                                + "\n\n"
                                + "\n".join(lines[1:])
                        )
                    else:
                        new_text_raw = content + "\n\n" + original
                    new_text = _normalize_newlines(new_text_raw)
                    if _contains_suspicious_control_chars(new_text):
                        new_text = _strip_suspicious_control_chars(new_text)
                        edit_logs.append(
                            {
                                "file": file_rel,
                                "operation": op,
                                "reason": "resulting content contained suspicious control characters which were stripped",
                            }
                        )

                    if _normalize_newlines(original) == new_text:
                        edit_logs.append(
                            {
                                "file": file_rel,
                                "operation": op,
                                "reason": "prepend produced no effective change",
                            }
                        )
                        continue

                    _safe_write_text(target_path, new_text)
                    touched.append(str(target_path.relative_to(PROJECT_ROOT)))
                    edit_logs.append(
                        {
                            "file": file_rel,
                            "operation": op,
                            "reason": "docstring-style block prepended to Python file",
                        }
                    )
                    continue

            prefix = _detect_comment_prefix(target_path)
            new_text_raw = f"{prefix}{content}\n\n{original}"
            new_text = _normalize_newlines(new_text_raw)
            if _contains_suspicious_control_chars(new_text):
                new_text = _strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "resulting content contained suspicious control characters which were stripped",
                    }
                )

            if _normalize_newlines(original) == new_text:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "prepend produced no effective change",
                    }
                )
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(PROJECT_ROOT)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "comment line prepended to file",
                }
            )

        else:
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": f"unknown operation {op!r}",
                }
            )

    scratch_file = SCRATCH_DIR / f"{base}.txt"
    scratch_file.write_text(
        "GhostFrog Chad execution\n"
        f"ID: {base}\n"
        f"Time: {now}\n"
        "Touched files:\n"
        + ("\n".join(touched) if touched else "(none)")
        + "\n\nEdit logs:\n"
        + (json.dumps(edit_logs, indent=2) if edit_logs else "(none)")
        + "\n",
        encoding="utf-8",
    )

    if touched:
        message = "Chad executed Bob's plan and modified files."
    else:
        if edits:
            message = (
                "Chad saw edits in the plan but skipped all of them; "
                "check edit_logs in the exec report for reasons."
            )
        else:
            message = "Chad did not modify any files (no edits in plan)."

    exec_report: dict = {
        "id": id_str,
        "date": date_str,
        "created_at": now,
        "actor": "chad",
        "kind": "exec_result",
        "status": "success",
        "touched_files": touched,
        "edits_requested": len(edits),
        "edit_logs": edit_logs,
        "message": message,
    }
    exec_path = QUEUE_DIR / f"{base}.exec.json"
    exec_path.write_text(json.dumps(exec_report, indent=2), encoding="utf-8")
    return exec_report


# ---------------------------------------------------------------------------
# Flask app + routes
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/chat", methods=["GET"])
def chat_page():
    """
    Serve the main chat UI from ui/chat_ui.html.
    """
    if CHAT_TEMPLATE_PATH.exists():
        html = CHAT_TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        html = "<h1>GhostFrog Bob/Chad UI</h1><p>chat_ui.html is missing.</p>"
    return render_template_string(html)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    One round trip:
      user → Bob(plan) → Chad(exec) → Bob(summary).
    """
    data = request.get_json(silent=True) or {}
    raw_message = (data.get("message") or "").strip()

    if not raw_message:
        return jsonify(
            {"messages": [{"role": "bob", "text": "I didn’t receive any command."}]}
        )

    message = raw_message
    tools_enabled = True
    prefix = "#bob no-tools"
    if message.lower().startswith(prefix):
        tools_enabled = False
        message = message[len(prefix):].lstrip()

    if not message:
        return jsonify(
            {"messages": [{"role": "bob", "text": "I didn’t receive any command."}]}
        )

    id_str, date_str, base = next_message_id()
    user_path = QUEUE_DIR / f"{base}.user.txt"
    user_path.write_text(message + "\n", encoding="utf-8")

    plan = bob_build_plan(id_str, date_str, base, message, tools_enabled=tools_enabled)

    # If Bob planned a codemod, refine with real file contents
    task = plan.get("task") or {}
    if task.get("type") == "codemod":
        original_edits = task.get("edits") or []
        files_for_context: set[str] = set()
        for e in original_edits:
            rel = e.get("file")
            if rel:
                files_for_context.add(rel)

        file_contexts: dict[str, str] = {}
        for rel in files_for_context:
            target = (PROJECT_ROOT / rel).resolve()
            try:
                target.relative_to(PROJECT_ROOT)
            except ValueError:
                continue
            if not target.exists() or not target.is_file():
                continue
            try:
                raw = target.read_text(encoding="utf-8")
            except Exception:
                continue
            file_contexts[rel] = raw

        if file_contexts:
            refined_task = bob_refine_codemod_with_files(
                user_text=message,
                base_task=task,
                file_contexts=file_contexts,
            )
            plan["task"] = refined_task
            task = refined_task  # keep in sync

    exec_report = chad_execute_plan(id_str, date_str, base, plan)

    # Common task info
    task = plan.get("task") or {}
    task_type = task.get("type", "analysis")
    summary = task.get("summary", message)
    analysis_file = task.get("analysis_file") or ""
    edits = task.get("edits") or []
    tool_obj = task.get("tool") or {}

    ui_messages = [
        {"role": "bob", "text": f"Bob: thinking… (id {base})"},
        {"role": "bob", "text": f"Bob: Plan → {summary}"},
    ]

    # --------------------------------------------------
    # TOOL
    # --------------------------------------------------
    if tool_obj and task_type == "tool":
        tool_name = tool_obj.get("name") or exec_report.get("tool_name") or ""
        tool_result = exec_report.get("tool_result", "")
        tool_message = exec_report.get("message", "Chad ran a tool.")

        if tool_name == "send_email" and tool_result:
            ui_messages.append({"role": "bob", "text": tool_result})
            ui_messages.append({"role": "chad", "text": tool_message})
        else:
            ui_messages.append({"role": "chad", "text": tool_message})
            if tool_result:
                ui_messages.append({"role": "bob", "text": tool_result})
            else:
                ui_messages.append(
                    {
                        "role": "bob",
                        "text": "The tool did not return any result.",
                    }
                )

        ui_messages.append(
            {
                "role": "bob",
                "text": (
                    "Bob: Done (tool).\n"
                    f"Files created:\n"
                    f"  - data/queue/{base}.user.txt\n"
                    f"  - data/queue/{base}.plan.json\n"
                    f"  - data/queue/{base}.exec.json\n"
                    f"Scratch note: data/scratch/{base}.txt"
                ),
            }
        )

    # --------------------------------------------------
    # PURE CHAT (no tool, no edits, no analysis file)
    # --------------------------------------------------
    elif not analysis_file and not edits and not tool_obj:
        answer = bob_simple_chat(message)
        ui_messages.append({"role": "bob", "text": answer})
        ui_messages.append(
            {
                "role": "bob",
                "text": (
                    "Bob: Done (chat-only).\n"
                    f"Files created:\n"
                    f"  - data/queue/{base}.user.txt\n"
                    f"  - data/queue/{base}.plan.json\n"
                    f"  - data/queue/{base}.exec.json\n"
                    f"Scratch note: data/scratch/{base}.txt"
                ),
            }
        )

    # --------------------------------------------------
    # ANALYSIS
    # --------------------------------------------------
    elif task_type == "analysis":
        ui_messages.append(
            {
                "role": "chad",
                "text": exec_report.get("message", "Chad fetched file for Bob."),
            }
        )
        snippet = exec_report.get("analysis_snippet", "")
        review = bob_answer_with_context(message, plan, snippet)
        ui_messages.append({"role": "bob", "text": review})
        ui_messages.append(
            {
                "role": "bob",
                "text": (
                    "Bob: Done (analysis).\n"
                    f"Files created:\n"
                    f"  - data/queue/{base}.user.txt\n"
                    f"  - data/queue/{base}.plan.json\n"
                    f"  - data/queue/{base}.exec.json\n"
                    f"Scratch note: data/scratch/{base}.txt"
                ),
            }
        )

    # --------------------------------------------------
    # CODEMOD
    # --------------------------------------------------
    else:
        touched_files = exec_report.get("touched_files") or []
        ui_messages.append({"role": "chad", "text": "Chad: working on Bob's plan…"})
        ui_messages.append(
            {
                "role": "chad",
                "text": exec_report.get("message", "Chad executed Bob's plan."),
            }
        )

        if touched_files:
            pretty = "\n".join(f" - {f}" for f in touched_files)
            ui_messages.append({"role": "chad", "text": f"Chad edited:\n{pretty}"})

            first_rel = touched_files[0]
            try:
                target_path = (PROJECT_ROOT / first_rel).resolve()
                target_path.relative_to(PROJECT_ROOT)
                content = target_path.read_text(encoding="utf-8")
                if len(content) > 16000:
                    snippet = content[:16000] + "\n\n... (truncated)"
                else:
                    snippet = content
                ui_messages.append(
                    {
                        "role": "bob",
                        "text": f"Here is the updated {first_rel}:\n\n{snippet}",
                    }
                )
            except Exception:
                pass

        ui_messages.append(
            {
                "role": "bob",
                "text": (
                    "Bob: Done.\n"
                    f"Files created:\n"
                    f"  - data/queue/{base}.user.txt\n"
                    f"  - data/queue/{base}.plan.json\n"
                    f"  - data/queue/{base}.exec.json\n"
                    f"Scratch note: data/scratch/{base}.txt"
                ),
            }
        )

    # --------------------------------------------------------------
    # Unified history logging for ALL job types
    # --------------------------------------------------------------
    try:
        result_label = "success"
        tests_label = "not_run"
        error_summary = None

        msg_text = (exec_report.get("message") or "").lower()
        edits_requested = exec_report.get("edits_requested", len(edits))
        touched_files = exec_report.get("touched_files") or []
        edit_logs = exec_report.get("edit_logs") or []

        # Base heuristic for failure
        if (
            "failed" in msg_text
            or "error" in msg_text
            or "unknown tool" in msg_text
        ):
            result_label = "fail"
            error_summary = exec_report.get("message")

        # Codemod-specific heuristics
        if task_type == "codemod":
            if edits_requested and not touched_files:
                result_label = "fail"
                reasons: list[str] = []
                for e in edit_logs:
                    r = (e.get("reason") or "").strip()
                    if r and r not in reasons:
                        reasons.append(r)
                    if len(reasons) >= 3:
                        break
                error_summary = (
                    "; ".join(reasons)
                    if reasons
                    else "codemod edits requested but no files were modified"
                )
            else:
                serious_keywords = (
                    "escapes project jail",
                    "does not exist",
                    "not utf-8",
                    "not UTF-8",
                    "unknown operation",
                )
                serious_reasons: list[str] = []
                for e in edit_logs:
                    r = (e.get("reason") or "").lower()
                    if any(k in r for k in serious_keywords):
                        serious_reasons.append(e.get("reason") or r)
                if serious_reasons:
                    result_label = "fail"
                    error_summary = "; ".join(serious_reasons[:3])

        log_history_record(
            target="ghostfrog",
            result=result_label,
            tests=tests_label,
            error_summary=error_summary,
            human_fix_required=result_label != "success",
            extra={
                "id": id_str,
                "base": base,
                "user_text": message,          # 👈 what repair_then_retry needs
                "tools_enabled": tools_enabled,
                "touched_files": touched_files,
                "task_type": task_type,
                "tool_name": (task.get("tool") or {}).get("name"),
            },
        )

        # If this job clearly failed, kick off an automatic self-repair + retry
        if result_label != "success":
            _auto_repair_then_retry_async()

    except Exception:
        # Never let logging break the chat flow
        pass

    return jsonify({"messages": ui_messages})


# ---------------------------------------------------------------------------
# Run tests before starting server
# ---------------------------------------------------------------------------


def run_tests_on_startup() -> bool:
    """
    Run pytest before starting the web app.

    Returns True if tests pass (or pytest missing), False if they fail.
    """
    try:
        import pytest
    except ImportError:
        print("[Bob/Chad] pytest not installed; skipping tests.")
        return True

    print("[Bob/Chad] Running test suite (pytest) before starting server...")
    result = pytest.main(["-q", "tests"])
    if result != 0:
        print(f"[Bob/Chad] Tests FAILED (exit code {result}); not starting server.")
        return False

    print("[Bob/Chad] Tests passed; starting server.")
    return True


if __name__ == "__main__":
    if run_tests_on_startup():
        print("[Bob/Chad] Web UI starting on http://127.0.0.1:8765/chat")
        app.run(host="127.0.0.1", port=8765)
