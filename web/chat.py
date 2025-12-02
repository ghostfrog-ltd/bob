# web/chat.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any, Dict, List

from flask import Blueprint, jsonify, request, render_template_string, send_from_directory


def create_chat_blueprint(
    *,
    chat_template_path: Path,
    project_root: Path,
    queue_dir: Path,
    scratch_dir: Path,
    next_message_id: Callable[[], tuple[str, str, str]],
    bob_build_plan: Callable[..., dict],
    bob_refine_codemod_with_files: Callable[..., dict],
    bob_simple_chat: Callable[[str], str],
    bob_answer_with_context: Callable[[str, dict, str], str],
    chad_execute_plan: Callable[[str, str, str, dict], dict],
    log_history_record: Callable[..., Any],
    auto_repair_fn: Callable[[], None],
) -> Blueprint:
    """
    Build the 'chat' blueprint, wiring in all non-HTTP dependencies via DI.
    """
    bp = Blueprint("chat", __name__)

    @bp.route("/<path:filename>")
    def serve_ui_files(filename: str):
        """
        Serve arbitrary files from the 'ui' directory.
        Works for CSS, JS, images, etc.
        No hard-coded filenames.
        """
        ui_dir = project_root / "ui"
        return send_from_directory(str(ui_dir), filename)

    @bp.route("/chat", methods=["GET"])
    def chat_page():
        """
        Serve the main chat UI from ui/chat_ui.html.
        """
        if chat_template_path.exists():
            html = chat_template_path.read_text(encoding="utf-8")
        else:
            html = "<h1>GhostFrog Bob/Chad UI</h1><p>chat_ui.html is missing.</p>"
        return render_template_string(html)

    @bp.route("/api/chat", methods=["POST"])
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
        user_path = queue_dir / f"{base}.user.txt"
        user_path.write_text(message + "\n", encoding="utf-8")

        plan = bob_build_plan(
            id_str,
            date_str,
            base,
            message,
            tools_enabled=tools_enabled,
        )

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
                target = (project_root / rel).resolve()
                try:
                    target.relative_to(project_root)
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

        # <-- NEW: unify touched_files here so we can send it back to the UI
        touched_files: List[str] = exec_report.get("touched_files") or []

        ui_messages: List[Dict[str, str]] = [
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
                    target_path = (project_root / first_rel).resolve()
                    target_path.relative_to(project_root)
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
                        "not-utf-8",
                        "not utf-8",
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
                    "user_text": message,  # what repair_then_retry needs
                    "tools_enabled": tools_enabled,
                    "touched_files": touched_files,
                    "task_type": task_type,
                    "tool_name": (task.get("tool") or {}).get("name"),
                },
            )

            # If this job clearly failed, kick off an automatic self-repair + retry
            if result_label != "success":
                auto_repair_fn()

        except Exception:
            # Never let logging break the chat flow
            pass

        # <-- IMPORTANT: include touched_files + task_type so the browser can decide to reload
        return jsonify(
            {
                "messages": ui_messages,
                "touched_files": touched_files,
                "task_type": task_type,
            }
        )

    return bp
