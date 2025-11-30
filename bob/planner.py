# bob/planner.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from helpers.prompts import get_prompt
from helpers.tools_prompt import describe_tools_for_prompt
from .config import get_openai_client, get_model_name
from .schema import BOB_PLAN_SCHEMA


def bob_build_plan(
    id_str: str,
    date_str: str,
    base: str,
    user_text: str,
    queue_dir: Optional[Path] = None,
    *,
    tools_enabled: bool = True,
) -> Dict[str, Any]:
    """
    Build a structured plan for Chad to execute.

    task.type can be:
        - 'chat'     → just answer, no file / tool / edits
        - 'tool'     → call a specific local tool via Chad
        - 'analysis' → review/explain an existing file (no edits)
        - 'codemod'  → Chad may edit files

    NOTE:
        - queue_dir is optional; if provided, we will also write
          `{base}.plan.json` into that directory for debugging/inspection.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    client = get_openai_client()

    # ------------------------------------------------------------------
    # Stub mode when there is no API key / client
    # ------------------------------------------------------------------
    if client is None:
        plan: Dict[str, Any] = {
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
        if queue_dir is not None:
            (queue_dir / f"{base}.plan.json").write_text(
                json.dumps(plan, indent=2), encoding="utf-8"
            )
        return plan

    # ------------------------------------------------------------------
    # Tool mode guidance
    # ------------------------------------------------------------------
    if tools_enabled:
        tool_mode_text = (
            "Tools ARE ENABLED for this request. You should choose task_type='tool' whenever "
            "the user is asking you to interact with the live project/filesystem, write notes, "
            "run a script, or send email — even if they do NOT mention tool names.\n"
        )
    else:
        tool_mode_text = (
            "Tools ARE DISABLED for this request. You MUST NOT choose task_type='tool', and "
            "you MUST leave the 'tool' object empty. Handle the request purely as 'chat', "
            "'analysis', or 'codemod'.\n"
        )

    tools_block = describe_tools_for_prompt()

    # ------------------------------------------------------------------
    # System prompt (loaded from markdown)
    # ------------------------------------------------------------------
    system_template = get_prompt("bob_planner_system")
    system_prompt = system_template.format(
        TOOL_MODE_TEXT=tool_mode_text,
        TOOLS_BLOCK=tools_block,
        BOB_PLAN_SCHEMA=json.dumps(BOB_PLAN_SCHEMA, indent=2),
    )

    # ------------------------------------------------------------------
    # Call OpenAI to build the plan
    # ------------------------------------------------------------------
    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            text={"format": {"type": "json_object"}},
        )

        raw = (resp.output_text or "").strip()
        # Try to recover a single JSON object if extra text sneaks in.
        first = raw.find("{")
        last = raw.rfind("}")
        if first != -1 and last != -1:
            raw = raw[first : last + 1]

        body = json.loads(raw)

        task_type = body.get("task_type", "analysis")
        summary = (body.get("summary") or user_text).strip()
        edits = body.get("edits") or []
        analysis_file = body.get("analysis_file") or ""
        tool_obj = body.get("tool") or {}
    except Exception as e:  # noqa: BLE001
        task_type = "analysis"
        summary = f"(STUB – OpenAI error: {e!r}) Handle user request: {user_text}"
        edits = []
        analysis_file = ""
        tool_obj = {}

    plan: Dict[str, Any] = {
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

    if queue_dir is not None:
        (queue_dir / f"{base}.plan.json").write_text(
            json.dumps(plan, indent=2), encoding="utf-8"
        )

    return plan


def bob_refine_codemod_with_files(
    user_text: str,
    base_task: Dict[str, Any],
    file_contexts: Dict[str, str],
) -> Dict[str, Any]:
    """
    Second-pass planner for codemods: refine an existing task given real file contents.

    Args:
        user_text: Original user request.
        base_task: Initial codemod-style task dict from bob_build_plan.
        file_contexts: Mapping of relative file path → file contents.

    Returns:
        A new task dict (type='codemod') with refined edits, or the original
        base_task on error/fallback.
    """
    client = get_openai_client()
    if client is None:
        return base_task

    if not file_contexts:
        return base_task

    files_blob_lines: list[str] = []
    for rel_path, contents in file_contexts.items():
        files_blob_lines.append(
            f"===== FILE: {rel_path} =====\n{contents}\n===== END FILE =====\n"
        )
    files_blob = "\n".join(files_blob_lines)

    # ------------------------------------------------------------------
    # Refinement prompt (loaded from markdown)
    # ------------------------------------------------------------------
    refine_template = get_prompt("bob_planner_refine_codemod")
    refine_prompt = refine_template.format(
        USER_TEXT=user_text,
        BOB_PLAN_SCHEMA=json.dumps(BOB_PLAN_SCHEMA, indent=2),
    )

    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": refine_prompt},
                {
                    "role": "user",
                    "content": (
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
            raw = raw[first : last + 1]

        body = json.loads(raw)

        summary = (body.get("summary") or base_task.get("summary", "")).strip()
        edits = body.get("edits") or []

        return {
            "type": "codemod",
            "summary": summary or base_task.get("summary", ""),
            "analysis_file": "",
            "edits": edits,
            "tool": {},
        }
    except Exception as e:  # noqa: BLE001
        fallback = dict(base_task)
        fallback.setdefault(
            "summary",
            f"{base_task.get('summary', '')} (codemod refinement failed: {e!r})",
        )
        return fallback
