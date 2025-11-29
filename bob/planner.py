# bob/planner.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config import get_openai_client, get_model_name
from .schema import BOB_PLAN_SCHEMA
from .tools_registry import describe_tools_for_prompt


def bob_build_plan(
    id_str: str,
    date_str: str,
    base: str,
    user_text: str,
    queue_dir: Path,
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
    # System prompt
    # ------------------------------------------------------------------
    system_prompt = (
        "You are Bob, a senior reasoning model orchestrating a local coder called Chad.\n"
        "The user is working on a Python / GhostFrog project.\n\n"
        "USER INTENT RULES\n"
        "- If the user says phrases like: 'show me', 'what does', 'explain', 'tell me', "
        "'describe', you MUST treat the request as INFORMATION ONLY. Do NOT change files, "
        "do NOT propose changes. Respond with an explanation or, if asked, a preview of code.\n"
        "- If the user says phrases like: 'add', 'fix', 'change', 'implement', 'update', "
        "'modify', 'stop doing', 'make it so', you MUST treat the request as a DIRECT CODING "
        "ORDER. Do NOT ask for confirmation first. Apply the change immediately and show a "
        "unified diff afterward.\n"
        "- Do NOT confuse the two behaviours. 'SHOW' means NO CHANGES. 'DO' means MAKE CHANGES "
        "without asking.\n"
        "- When showing code, ONLY show the specific function or small snippet requested. "
        "NEVER dump entire files unless the user explicitly says 'show the whole file'.\n\n"
        "FUNCTION MODIFICATION RULES\n"
        "- When the user asks you to change a specific function (for example: 'run()', 'main()', "
        "'send_alert'), you MUST:\n"
        "    * Locate the existing definition of that function in the specified file.\n"
        "    * Modify that existing definition in-place.\n"
        "- You MUST NOT create a new function with the same name.\n"
        "- You MUST NOT introduce wrappers unless explicitly asked.\n"
        "- You MUST NOT monkey patch.\n"
        "- You MUST NOT rebind function names at the bottom of files.\n"
        "- If the function cannot be found, state that in the plan.\n\n"
        "CHANGE REQUEST INTERPRETATION RULES\n"
        "- When the user describes a function at a path and asks for behaviour changes, "
        "treat that as a codemod request.\n"
        "- In those cases task_type MUST be 'codemod'.\n"
        "- Edit the specified file only.\n\n"
        "PRESERVE EXISTING LOGIC RULES\n"
        "- Default behaviour: minimal, surgical modification.\n"
        "- Do NOT rewrite unrelated logic.\n"
        "- Do NOT replace whole function bodies unless explicitly asked.\n\n"
        "STRING / LOG MESSAGE RULES\n"
        "- Treat all existing string literals as public interface.\n"
        "- Preserve EXACT punctuation, Unicode, emojis, and placeholders.\n"
        "- NEVER normalise Unicode.\n\n"
        "SPECIAL FILE RULES – roi_listings.py\n"
        "- Be extremely careful in this file.\n"
        "- Do NOT change existing log messages.\n"
        "- Only filter or guard logic around email digest behaviour when asked.\n\n"
        "NO-REFORMAT / DIFF RULES\n"
        "- Do NOT reorder imports.\n"
        "- Do NOT reformat files.\n"
        "- Maintain structure.\n"
        "- Only small diffs.\n\n"
        "GENERAL EXECUTION BEHAVIOUR\n"
        "- Direct instructions = approved work.\n"
        "- Do NOT ask permission unless user explicitly asks.\n"
        "- Perform codemod then show diff unless told otherwise.\n\n"
        f"{tool_mode_text}"
        "The user does NOT remember tool names. Infer the correct tool.\n\n"
        "Here is the list of tools you may use:\n\n"
        f"{tools_block}\n\n"
        "SCRIPT EXECUTION RULE\n"
        "- When the user asks you to run a Python script (e.g. 'run this', 'run X.py', "
        "'execute this script'), you MUST choose task_type='tool' and use the "
        "'run_python_script' tool.\n\n"
        "PLAN OUTPUT RULES\n"
        "- Your output MUST be a single JSON object matching BOB_PLAN_SCHEMA.\n"
        "- For tools, set task_type='tool' and fill the 'tool' object with:\n"
        "    * 'name': the tool name\n"
        "    * 'args': the arguments dict\n"
        "- Do NOT invent extra top-level keys.\n"
        "- Do NOT output multiple JSON objects or any commentary.\n\n"
        "BOB_PLAN_SCHEMA (for reference):\n"
        f"{json.dumps(BOB_PLAN_SCHEMA, indent=2)}\n"
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

    refine_prompt = (
        "You are Bob, refining your previous codemod plan now that you have the "
        "actual contents of the files from disk.\n\n"
        "The user request is:\n"
        f"{user_text}\n\n"
        "You are given the current contents of the files you are allowed to edit.\n"
        "You MUST:\n"
        "- Keep task_type = 'codemod'.\n"
        "- Preserve all existing behaviour unless the user explicitly asked for a rewrite.\n"
        "- Modify existing functions IN-PLACE instead of wrapping or duplicating them.\n"
        "- Produce the MINIMAL edits necessary to satisfy the user request.\n"
        "- Do NOT reorder imports, do NOT reformat, and do NOT touch unrelated lines.\n"
        "- For Python files where you are modifying an existing function, you may use "
        "'create_or_overwrite_file' but the updated content MUST be identical to the "
        "original everywhere except the specific few lines that implement the requested "
        "change.\n\n"
        "Here is the JSON schema you MUST follow for the task object:\n"
        f"{json.dumps(BOB_PLAN_SCHEMA, indent=2)}\n\n"
        "Return ONLY a single JSON object. Do NOT include any extra commentary.\n"
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
