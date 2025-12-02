# chad/executor.py

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bob.tools_registry import TOOL_REGISTRY
from helpers.text import (
    safe_write_text,
    normalize_newlines,
    contains_suspicious_control_chars,
    strip_suspicious_control_chars,
    detect_comment_prefix,
)
from chad.tools import run_tool as run_chad_tool


# ---------------------------------------------------------------------------
# Main entrypoint – used by app.py (and can be used by tests)
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
      - For task.type == 'tool'     → runs a local tool via chad.tools.
      - For task.type == 'analysis' → reads a file snippet for Bob.
      - For task.type == 'codemod'  → applies edits INSIDE project_root.
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

        # Sanity-check against Bob's registry so he can't invent random tools
        if not tool_name or tool_name not in TOOL_REGISTRY:
            message = (
                f"Chad was asked to run tool {tool_name!r}, but it is not registered "
                "in bob.tools_registry. No tool was executed."
            )
        else:
            result = run_chad_tool(
                tool_name,
                tool_args,
                project_root=project_root,
                notes_dir=notes_dir,
                scratch_dir=scratch_dir,
            )
            if result is None:
                message = (
                    f"Chad was asked to run tool {tool_name!r}, but there is no "
                    "implementation registered in chad.tools. No tool was executed."
                )
            else:
                tool_result, message = result

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
            # useful for debugging / tests
            "tool_args": tool_args,
            "tool_result": tool_result,
            "message": message,
        }
        exec_path = queue_dir / f"{base}.exec.json"
        exec_path.write_text(json.dumps(exec_report, indent=2), encoding="utf-8")
        return exec_report

    # ------------------------------------------------------------------
    # ANALYSIS branch
    # ------------------------------------------------------------------
    if task_type != "codemod":
        analysis_file = task.get("analysis_file") or ""
        analysis_snippet = ""
        target_rel: Optional[str] = None

        if analysis_file:
            target_path = (project_root / analysis_file).resolve()
            try:
                target_path.relative_to(project_root)
            except ValueError:
                target_path = None

            if target_path is not None and target_path.exists():
                try:
                    raw = target_path.read_text(encoding="utf-8")
                except Exception:
                    raw = ""
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

        target_path = (project_root / file_rel).resolve()
        try:
            target_path.relative_to(project_root)
        except ValueError:
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "target path escapes project jail",
                }
            )
            continue

        # Decide how to handle non-existent files based on the operation.
        # Some ops (create_or_overwrite_file, replace, append_to_bottom) can
        # legitimately create a new file; others (like prepend_comment) require it.
        if target_path.exists():
            try:
                original = target_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "could not read target file from disk",
                    }
                )
                continue
        else:
            if op in ("create_or_overwrite_file", "replace", "append_to_bottom"):
                # Treat this as creating a new file; original content is empty.
                original = ""
            else:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "target file does not exist on disk",
                    }
                )
                continue

        if op == "create_or_overwrite_file":
            new_text = normalize_newlines(content)

            if contains_suspicious_control_chars(new_text):
                cleaned = strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": (
                            "new content contained suspicious control characters "
                            "which were stripped"
                        ),
                    }
                )
                new_text = cleaned

            norm_old = normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "new content is identical to existing file",
                    }
                )
                continue

            safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "file overwritten with new content",
                }
            )

        elif op == "replace":
            # Overwrite the entire file contents with `content`.
            new_text = normalize_newlines(content)

            if contains_suspicious_control_chars(new_text):
                cleaned = strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": (
                            "new content contained suspicious control characters "
                            "which were stripped"
                        ),
                    }
                )
                new_text = cleaned

            norm_old = normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "replace produced no effective change",
                    }
                )
                continue

            safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "file replaced with new content",
                }
            )

        elif op == "append_to_bottom":
            new_text_raw = original.rstrip() + "\n\n" + content + "\n"
            new_text = normalize_newlines(new_text_raw)

            if contains_suspicious_control_chars(new_text):
                cleaned = strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": (
                            "resulting content contained suspicious control "
                            "characters which were stripped"
                        ),
                    }
                )
                new_text = cleaned

            norm_old = normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "append produced no effective change",
                    }
                )
                continue

            safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
            edit_logs.append(
                {
                    "file": file_rel,
                    "operation": op,
                    "reason": "content appended to bottom of file",
                }
            )

        elif op == "prepend_comment":
            prefix = detect_comment_prefix(target_path)
            new_text_raw = f"{prefix}{content}\n\n{original}"
            new_text = normalize_newlines(new_text_raw)

            if contains_suspicious_control_chars(new_text):
                cleaned = strip_suspicious_control_chars(new_text)
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": (
                            "resulting content contained suspicious control "
                            "characters which were stripped"
                        ),
                    }
                )
                new_text = cleaned

            norm_old = normalize_newlines(original)
            norm_new = new_text
            if norm_old == norm_new:
                edit_logs.append(
                    {
                        "file": file_rel,
                        "operation": op,
                        "reason": "prepend produced no effective change",
                    }
                )
                continue

            safe_write_text(target_path, new_text)
            touched.append(str(target_path.relative_to(project_root)))
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

    scratch_file = scratch_dir / f"{base}.txt"
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

    exec_path = queue_dir / f"{base}.exec.json"
    exec_path.write_text(json.dumps(exec_report, indent=2), encoding="utf-8")
    return exec_report
