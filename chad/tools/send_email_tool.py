# chad/tools/send_email_tool.py
from __future__ import annotations

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from helpers.jail import resolve_in_project_jail

from . import register_tool, ToolResult


def _run_send_email(
    args: Dict[str, Any],
    project_root: Path,
    notes_dir: Path,
    scratch_dir: Path,  # unused
) -> ToolResult:
    env_to = (
        os.getenv("SMTP_TO")
        or os.getenv("SMTP_TEST_TO")
        or ""
    ).strip()
    to_addr = env_to

    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "")

    attachments_in_args = "attachments" in args
    attachments = args.get("attachments")
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
        return "", message
    if not smtp_host or not from_addr:
        message = (
            "Chad was asked to send_email, but SMTP settings are incomplete "
            "(need at least SMTP_HOST and SMTP_FROM or SMTP_USERNAME)."
        )
        return "", message

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
                attach_path = resolve_in_project_jail(rel_str, project_root)
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
        return tool_result, message
    except Exception as e:  # noqa: BLE001
        message = f"Chad failed to send_email due to error: {e!r}"
        return "", message


register_tool("send_email", _run_send_email)
