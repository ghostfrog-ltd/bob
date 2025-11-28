# chad/executor.py
#!/usr/bin/env python3
from __future__ import annotations

import mimetypes
import os
import smtplib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

from bob.tools_registry import TOOL_REGISTRY

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _normalize_newlines(text: str) -> str:
    """
    Normalise all line endings to LF ('\n') so git diffs stay sane.
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
    Lightweight strip for a couple of problematic chars that have shown up
    in practice. We keep this separate from __strip_suspicious_control_chars
    so we can choose behaviour depending on context.
    """
    return text.replace("\x0b", "").replace("\x0c", "")


def __strip_suspicious_control_chars(text: str) -> str:
    """
    Remove ASCII control characters other than newline, carriage-return, or tab.

    This lets Chad accept LLM output that accidentally contains things like
    vertical-tab or form-feed by stripping them instead of skipping the edit.
    """
    cleaned_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if code < 32 and ch not in ("\n", "\r", "\t"):
            # strip the suspicious control char
            continue
        cleaned_chars.append(ch)
    return "".join(cleaned_chars)


def _safe_write_text(path: Path, text: str) -> None:
    """
    Write UTF-8 text with LF newlines only.

    - keeps encoding consistent
    - keeps line endings consistent
    - avoids BOMs
    """
    if not isinstance(text, str):
        text = str(text)

    text = _normalize_newlines(text)
    path.parent.mkdir(parents=True, exist_ok=True)

    # newline='\n' forces LF on disk
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _detect_comment_prefix(path: Path) -> str:
    """
    Very simple comment-style detector based on file extension.
    Used for the 'prepend_comment' operation.
    """
    ext = path.suffix.lower()
    if ext in {".py", ".sh"}:
        return "# "
    if ext in {".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h"}:
        return "// "
    if ext in {".php"}:
        return "// "
    return "# "


def _resolve_in_project_jail(relative_path: str, project_root: Path) -> Path | None:
    """
    Resolve a relative path against project_root, enforcing the jail.

    Returns a Path or None if the path escapes the jail.
    """
    if not relative_path:
        relative_path = "."
    target = (project_root / relative_path).resolve()
    try:
        target.relative_to(project_root)
    except ValueError:
        return None
    return target


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


# ---------------------------------------------------------------------------
# Main entrypoint – used by tests and by app.py
# ---------------------------------------------------------------------------

def chad_execute_plan(
    id_str: str,
    date_str: str,
    base: str,
    plan: dict,
    *,
    project_root: Path,
    queue_dir: Path,
    scratch_dir: Path,
    notes_dir: Path,
) -> dict:
    """
    Chad executes Bob's plan.

    Rules:
      - Only acts on task.type == 'codemod' for file edits.
      - For 'tool', runs a local tool (e.g. system datetime, list_files, SMTP).
      - For 'analysis', reads a file for Bob to review.
      - Only edits files INSIDE project_root.
      - Returns a dict exec_report; NEVER returns None.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    queue_dir.mkdir(parents=True, exist_ok=True)
    notes_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    task = plan.get("task") or {}
    task_type = task.get("type", "analysis")
    edits = task.get("edits") or []
    tool_obj = task.get("tool") or {}

    touched: list[str] = []

    # ------------------------------------------------------------------
    # TOOL branch – use local system capabilities (e.g. datetime, FS, SMTP)
    # ------------------------------------------------------------------
    if task_type == "tool":
        tool_name = tool_obj.get("name") or ""
        tool_args = tool_obj.get("args") or {}
        tool_result = ""
        message = ""

        # Optional: sanity-check against registry so Bob can't invent random tools
        if tool_name and tool_name not in TOOL_REGISTRY:
            message = (
                f"Chad was asked to run tool {tool_name!r}, but it is not registered "
                "in bob.tools_registry. No tool was executed."
            )
            tool_result = ""
            scratch_file = scratch_dir / f"{base}.txt"
            scratch_file.write_text(
                "GhostFrog Chad tool execution\n"
                f"ID: {base}\n"
                f"Time: {now}\n"
                f"Tool name: {tool_name or '(none)'}\n"
                f"Tool args: {tool_args}\n"
                "Tool result:\n(no result – unknown tool)\n",
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
                "tool_args": tool_args,
                "tool_result": tool_result,
                "message": message,
            }
            exec_path = queue_dir / f"{base}.exec.json"
            exec_path.write_text(str(exec_report), encoding="utf-8")
            return exec_report

        # --- get_current_datetime ---
        if tool_name == "get_current_datetime":
            now_local = datetime.now().astimezone()
            dt_str = now_local.strftime("%A, %d %B %Y, %H:%M:%S %Z (%z)")
            tool_result = f"Local system date and time: {dt_str}"
            message = "Chad ran tool 'get_current_datetime' using the system clock."

        # --- list_files ---
        elif tool_name == "list_files":
            rel_path = str(tool_args.get("path") or ".")
            recursive = bool(tool_args.get("recursive", False))
            try:
                max_entries = int(tool_args.get("max_entries", 200))
            except (TypeError, ValueError):
                max_entries = 200

            base_path = _resolve_in_project_jail(rel_path, project_root)
            if base_path is None or not base_path.exists():
                message = (
                    f"Chad tried to list_files at {rel_path!r} but the path was invalid "
                    "or outside the project jail."
                )
                tool_result = ""
            else:
                entries: list[dict] = []
                count = 0

                if recursive and base_path.is_dir():
                    for path in base_path.rglob("*"):
                        if count >= max_entries:
                            break
                        try:
                            rel = str(path.relative_to(project_root))
                        except ValueError:
                            continue
                        if path.is_dir():
                            entries.append(
                                {"path": rel, "type": "dir", "size": None}
                            )
                        else:
                            try:
                                size = path.stat().st_size
                            except OSError:
                                size = None
                            entries.append(
                                {"path": rel, "type": "file", "size": size}
                            )
                        count += 1
                elif base_path.is_dir():
                    for path in sorted(base_path.iterdir()):
                        if count >= max_entries:
                            break
                        try:
                            rel = str(path.relative_to(project_root))
                        except ValueError:
                            continue
                        if path.is_dir():
                            entries.append(
                                {"path": rel, "type": "dir", "size": None}
                            )
                        else:
                            try:
                                size = path.stat().st_size
                            except OSError:
                                size = None
                            entries.append(
                                {"path": rel, "type": "file", "size": size}
                            )
                        count += 1
                else:
                    try:
                        rel = str(base_path.relative_to(project_root))
                    except ValueError:
                        rel = base_path.name
                    try:
                        size = base_path.stat().st_size
                    except OSError:
                        size = None
                    entries.append(
                        {"path": rel, "type": "file", "size": size}
                    )

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

        # --- read_file ---
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

            target_path = _resolve_in_project_jail(rel_path, project_root)
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

        # --- markdown notes ---
        elif tool_name in {"create_markdown_note", "append_to_markdown_note"}:
            title = str(tool_args.get("title") or tool_args.get("name") or "").strip()
            content = str(tool_args.get("content") or "")
            slug = _slugify_for_markdown(title or "note")
            note_path = notes_dir / f"{slug}.md"

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

        # --- send_email ---
        elif tool_name == "send_email":
            # Force the 'to' address from environment, ignoring any user-supplied 'to'
            env_to = (
                os.getenv("SMTP_TO")
                or os.getenv("SMTP_TEST_TO")
                or ""
            ).strip()
            to_addr = env_to

            subject = str(tool_args.get("subject") or "").strip()
            body = str(tool_args.get("body") or "")

            attachments_in_args = "attachments" in tool_args
            attachments = tool_args.get("attachments")
            if attachments is None:
                attachments = []

            auto_note = False
            note_path: Optional[Path] = None
            note_rel_display: Optional[str] = None

            # Auto-attach most recent markdown note if none supplied at all
            if not attachments and not attachments_in_args:
                latest = None
                latest_mtime = None
                for p in notes_dir.glob("*.md"):
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
                        attachment_rel = str(latest.relative_to(project_root))
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
                            attach_path = _resolve_in_project_jail(rel_str, project_root)
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
                        f"Chad sent an email to {to_addr!r} with subject {subject!r}."
                    )
                except Exception as e:
                    message = f"Chad failed to send_email due to error: {e!r}"
                    tool_result = ""

        # --- run_python_script ---
        elif tool_name == "run_python_script":
            rel_path = str(tool_args.get("path") or "")
            args_list = tool_args.get("args") or []
            try:
                timeout = int(tool_args.get("timeout", 600))
            except (TypeError, ValueError):
                timeout = 600

            target_path = _resolve_in_project_jail(rel_path, project_root)
            if (
                target_path is None
                or not target_path.exists()
                or not target_path.is_file()
            ):
                message = (
                    f"Chad tried to run_python_script {rel_path!r} but the file does not exist, "
                    "is not a file, or is outside the project jail."
                )
                tool_result = ""
            else:
                try:
                    proc = subprocess.run(
                        ["python3", str(target_path), *[str(a) for a in args_list]],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                    tool_result = (
                        f"Exit code: {proc.returncode}\n\n"
                        f"STDOUT:\n{proc.stdout}\n\n"
                        f"STDERR:\n{proc.stderr}"
                    )
                    message = (
                        f"Chad ran run_python_script on {rel_path!r} "
                        f"with args {args_list!r} (exit code {proc.returncode})."
                    )
                except Exception as e:
                    message = f"Chad failed to run_python_script due to error: {e!r}"
                    tool_result = ""

        else:
            message = (
                f"Chad was asked to run an unknown tool: {tool_name!r}. "
                "No tool was executed."
            )
            tool_result = ""

        scratch_file = scratch_dir / f"{base}.txt"
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
            # IMPORTANT for tests: expose args & result
            "tool_args": tool_args,
            "tool_result": tool_result,
            "message": message,
        }
        exec_path = queue_dir / f"{base}.exec.json"
        exec_path.write_text(str(exec_report), encoding="utf-8")
        return exec_report

    # ------------------------------------------------------------------
    # ANALYSIS branch – minimal implementation (tests focus on tools)
    # ------------------------------------------------------------------
    if task_type != "codemod":
        analysis_file = task.get("analysis_file") or ""
        analysis_snippet = ""
        target_rel = None

        if analysis_file:
            target_path = (project_root / analysis_file).resolve()
            try:
                target_path.relative_to(project_root)
            except ValueError:
                target_path = None

            if target_path is not None and target_path.exists():
                raw = target_path.read_text(encoding="utf-8")
                analysis_snippet = raw[:16000]
                target_rel = str(target_path.relative_to(project_root))

        scratch_file = scratch_dir / f"{base}.txt"
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
        exec_path = queue_dir / f"{base}.exec.json"
        exec_path.write_text(str(exec_report), encoding="utf-8")
        return exec_report

    # ------------------------------------------------------------------
    # CODEMOD branch – stubbed enough for now (tests are about tools)
    # ------------------------------------------------------------------
    edit_logs: list[dict] = []

    # In future we can mirror your full codemod implementation.
    # For now, we just record that we saw edits.
    for edit in edits:
        file_rel = edit.get("file")
        op = edit.get("operation")
        content = edit.get("content", "")

        if not file_rel or not op:
            edit_logs.append({
                "file": file_rel or "(none)",
                "operation": op or "(none)",
                "reason": "missing file or operation in edit",
            })
            continue

        target_path = (project_root / file_rel).resolve()
        try:
            target_path.relative_to(project_root)
        except ValueError:
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": "target path escapes project jail",
            })
            continue

        if not target_path.exists():
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": "target file does not exist on disk",
            })
            continue

        original = _safe_read_text(target_path)

        if op == "create_or_overwrite_file":
            new_text = _normalize_newlines(content)

            if _contains_suspicious_control_chars(new_text):
                cleaned = _strip_suspicious_control_chars(new_text)
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "new content contained suspicious control characters which were stripped",
                })
                new_text = cleaned

            norm_old = _normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "new content is identical to existing file",
                })
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": "file overwritten with new content",
            })

        elif op == "append_to_bottom":
            new_text_raw = original.rstrip() + "\n\n" + content + "\n"
            new_text = _normalize_newlines(new_text_raw)

            if _contains_suspicious_control_chars(new_text):
                cleaned = _strip_suspicious_control_chars(new_text)
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "resulting content contained suspicious control characters which were stripped",
                })
                new_text = cleaned

            norm_old = _normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "append produced no effective change",
                })
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": "content appended to bottom of file",
            })

        elif op == "prepend_comment":
            prefix = _detect_comment_prefix(target_path)
            new_text_raw = f"{prefix}{content}\n\n{original}"
            new_text = _normalize_newlines(new_text_raw)

            if _contains_suspicious_control_chars(new_text):
                cleaned = _strip_suspicious_control_chars(new_text)
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "resulting content contained suspicious control characters which were stripped",
                })
                new_text = cleaned

            norm_old = _normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append({
                    "file": file_rel,
                    "operation": op,
                    "reason": "prepend produced no effective change",
                })
                continue

            _safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": "comment line prepended to file",
            })

        else:
            edit_logs.append({
                "file": file_rel,
                "operation": op,
                "reason": f"unknown operation {op!r}",
            })

    scratch_file = scratch_dir / f"{base}.txt"
    scratch_file.write_text(
        "GhostFrog Chad execution\n"
        f"ID: {base}\n"
        f"Time: {now}\n"
        "Touched files:\n"
        + ("\n".join(touched) if touched else "(none)")
        + "\n\nEdit logs:\n"
        + (str(edit_logs) if edit_logs else "(none)")
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

    exec_path = queue_dir / f"{base}.exec.json"
    exec_path.write_text(str(exec_report), encoding="utf-8")
    return exec_report
