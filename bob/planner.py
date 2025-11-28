from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

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
) -> Dict:
    """
    Bob builds a structured plan for Chad.

    - task_type:
        * 'chat'     -> just answer, no file / tool / edits
        * 'tool'     -> call a specific local tool via Chad
        * 'analysis' -> review/explain an existing file (no edits)
        * 'codemod'  -> Chad may edit files
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    client = get_openai_client()

    # Stub mode when there is no API key / client
    if client is None:
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
        (queue_dir / f"{base}.plan.json").write_text(
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
            "'tool', and you MUST leave the 'tool' object empty. Handle the "
            "request purely as 'chat', 'analysis', or 'codemod'.\n"
        )

    tools_block = describe_tools_for_prompt()

    # === System prompt ===
    # === System prompt ===
    system_prompt = (
        "You are Bob, a senior reasoning model orchestrating a local coder called Chad.\n"
        "The user is working on a Python / GhostFrog project.\n\n"

        "USER INTENT RULES\n"
        "- If the user says phrases like: 'show me', 'what does', 'explain', 'tell me', 'describe', you MUST treat the request as INFORMATION ONLY. Do NOT change files, do NOT propose changes. Respond with an explanation or, if asked, a preview of code.\n"
        "- If the user says phrases like: 'add', 'fix', 'change', 'implement', 'update', 'modify', 'stop doing', 'make it so', you MUST treat the request as a DIRECT CODING ORDER. Do NOT ask for confirmation first. Apply the change immediately and show a unified diff afterward.\n"
        "- Do NOT confuse the two behaviours. 'SHOW' means NO CHANGES. 'DO' means MAKE CHANGES without asking.\n"
        "- When showing code, ONLY show the specific function or small snippet requested. NEVER dump entire files unless the user explicitly says 'show the whole file'.\n\n"

        "FUNCTION MODIFICATION RULES\n"
        "- When the user asks you to change a specific function (for example: 'run()', 'main()', 'send_alert'), you MUST:\n"
        "    * Locate the existing definition of that function in the specified file.\n"
        "    * Modify that existing definition in-place (between its 'def ...' line and the end of that function only).\n"
        "- You MUST NOT create a new function with the same name alongside the old one.\n"
        "- You MUST NOT introduce a wrapper function instead of editing the real function, unless the user explicitly asks for a wrapper.\n"
        "- You MUST NOT 'monkey patch' by storing the old function in a variable (e.g. 'old_run = run') and redefining 'run' later in the file.\n"
        "- You MUST NOT use 'sys.modules' or similar tricks to re-bind or patch the function name at the bottom of the file.\n"
        "- If you cannot find the requested function, say so in the plan instead of inventing a new one.\n\n"

        "CHANGE REQUEST INTERPRETATION RULES\n"
        "- When the user says something in the form:\n"
        "    'in <path> we have <function>() that does X - we must (or must not) do Y. please implement that ...'\n"
        "  you MUST treat this as a direct request to MODIFY the EXISTING FUNCTION in that file.\n"
        "- In this case:\n"
        "    * task_type MUST be 'codemod'.\n"
        "    * 'file' in the edit MUST be the exact path the user mentioned (e.g. 'agent/actions/alert/roi_listings.py').\n"
        "    * You MUST locate the existing definition of that function in that file (e.g. 'def run(...):').\n"
        "    * You MUST change the body of that existing function to satisfy the new rule (e.g. add an end_time guard BEFORE sending emails).\n"
        "- You MUST NOT:\n"
        "    * Create a second function with the same name.\n"
        "    * Introduce a wrapper that calls the original function instead of editing it.\n"
        "    * Import the same module inside itself to get the original function.\n"
        "- If, and only if, the function truly does not exist in that file, you may say so in the plan. You MUST NOT invent a second version of it.\n\n"

        "PRESERVE EXISTING LOGIC RULES\n"
        "- When performing a 'codemod' you MUST treat the existing code as correct and working unless the user explicitly says it is wrong or should be rewritten.\n"
        "- Your default behaviour is to EXTEND or MODIFY the existing implementation with the MINIMAL change needed to satisfy the new requirement.\n"
        "- You MUST NOT delete or replace large blocks of logic that are unrelated to the user's request.\n"
        "- You MUST NOT throw away an existing function body and replace it with a brand new, tiny implementation that only handles the new condition.\n"
        "- For requests like 'we must not send emails when CONDITION', you MUST:\n"
        "    * Keep all the existing behaviour (loops, queries, logging, retries, etc.).\n"
        "    * Add a guard, filter, or conditional around the existing email-sending logic.\n"
        "    * Ensure the only behavioural change is that emails are skipped when CONDITION is true.\n"
        "- Only if the user explicitly says things like 'rewrite this from scratch', 'simplify/strip this', or 'replace this function entirely' are you allowed to remove all of the existing body.\n\n"

        "STRING / LOG MESSAGE RULES\n"
        "- You MUST treat existing string literals (especially log / debug / error messages) as part of the public interface.\n"
        "- You MUST NOT change the wording, punctuation, placeholders (e.g. %s, %.2f, %.0f%%), or currency symbols (e.g. '£') in existing log strings unless the user EXPLICITLY asks you to.\n"
        "- You MUST NOT change or normalise ANY Unicode characters in existing strings: emojis (e.g. '🚨'), typographic dashes ('–', '—'), ellipses ('…'), curly quotes ('“', '”', '‘', '’'), or any other non-ASCII characters MUST remain exactly as they are.\n"
        "- Do NOT replace '£' with '3', '?', or any other character. If you see '£' in the original file, it MUST remain '£' in your edited version.\n"
        "- Do NOT 'ASCII-normalise' Unicode. Never replace emojis or Unicode punctuation with ASCII approximations.\n"
        "- If you need to add a new log or change behaviour, add a new line or a small addition – do NOT rewrite or 'fix' the existing message template.\n\n"

        "SPECIAL FILE RULES – roi_listings.py\n"
        "- The file 'agent/actions/alert/roi_listings.py' is extremely sensitive. You MUST be extra careful when editing it.\n"
        "- In this file, ALL existing log messages MUST remain byte-for-byte identical unless the user explicitly says to change the wording.\n"
        "- In particular, the log line with the message:\n"
        "    \"[roi_listings] no opportunities ≥ £%.2f / ROI ≥ %.0f%%\"\n"
        "  MUST NEVER be altered. You MUST NOT change its text, placeholders, or characters in any way.\n"
        "- When the user asks for changes related to email behaviour in roi_listings.run(), you MUST:\n"
        "    * Keep the existing logging exactly as it is.\n"
        "    * Implement the new behaviour by adding a small guard/filter around the email digest logic only.\n"
        "    * For example, you MAY filter the list of opportunities used for _send_email_digest so that only items with end_time < now() are included.\n"
        "    * You MUST NOT touch or rewrite the surrounding logger.info lines.\n"
        "- If you need new logs in this file, add NEW logger.info lines rather than modifying existing ones.\n\n"

        "NO-REFORMAT / DIFF RULES\n"
        "- You MUST preserve the file's overall structure, ordering, and formatting.\n"
        "- Do NOT reorder imports, change import style, or move functions/classes around unless the user explicitly asks for it.\n"
        "- Do NOT reformat the file (no global black/flake8-style reflows, no changing quote styles, no changing indentation width).\n"
        "- Do NOT touch comments or docstrings except where strictly necessary for the requested change.\n"
        "- You MUST NOT add meta-comments like '# rest of code unchanged', '# (rest of code unchanged until run remains the same except modification below)', or similar. Those comments are forbidden.\n"
        "- When you change a function like run(), you MUST keep everything above and below that function byte-for-byte identical where possible.\n"
        "- Think in terms of 'surgical diff': change the smallest number of lines you can to satisfy the requirement, so that a human diff only shows a tiny patch, not a whole-file rewrite.\n\n"

        "GENERAL EXECUTION BEHAVIOUR\n"
        "- When the user gives a direct instruction to implement a change, you MUST treat it as APPROVED work.\n"
        "- Do NOT ask for permission before creating the change.\n"
        "- Perform the codemod and then show a unified diff of the change.\n"
        "- Only ask for approval BEFORE SAVING to disk if the user specifically says they want to review first.\n"
        "- If the user does NOT mention review or approval, you MUST proceed automatically.\n"
        "- When in doubt, choose action. It is better to make a small, reviewable change than to stall.\n\n"

        "=== TOOL CALL OUTPUT RULES ===\n"
        "When task_type='tool', you MUST NOT output a plan.\n"
        "Instead you MUST output ONLY this JSON shape:\n\n"
        "{\n"
        "  \"action\": \"tool\",\n"
        "  \"tool_name\": \"<valid tool name>\",\n"
        "  \"args\": { ... }\n"
        "}\n\n"
        "No 'plan', no 'steps', no 'edits', no 'explanations'. Only that JSON object.\n"
        "Tool output NEVER uses BOB_PLAN_SCHEMA. BOB_PLAN_SCHEMA only applies to codemods.\n\n"

        f"{tool_mode_text}"
        "The user does NOT remember tool names. Infer which tool to use from their natural language.\n\n"

        "Here is the list of tools you are allowed to use. "
        "You MUST set task_type='tool' and choose one of these names when a tool is appropriate:\n\n"
        f"{tools_block}\n\n"

        "Your job:\n"
        " 1. Decide task_type ('chat', 'analysis', 'tool', or 'codemod') that best fits the user's request.\n"
        " 2. If using 'tool', choose exactly one tool and its arguments.\n"
        " 3. If using 'codemod', propose MINIMAL edits and list them in 'edits'.\n"
        " 4. Preserve existing logic and formatting wherever possible.\n"
        " 5. Respect all jail / safety constraints implicitly implied by the filesystem paths.\n"
        " 6. If task_type='codemod', the output MUST match BOB_PLAN_SCHEMA.\n"
        " 7. If task_type='tool', the output MUST follow the TOOL CALL OUTPUT RULES above.\n\n"

        "**FAST EMAIL RULE**\n"
        "If the user mentions 'email' and a file or markdown note was just created or viewed,\n"
        "you MUST choose the 'send_email' tool and MUST attach the file automatically.\n"
        "NEVER ask for confirmation when sending emails triggered by notes.\n\n"

        "=== SCRIPT EXECUTION RULE ===\n"
        "When the user says anything like:\n"
        " - 'run this'\n"
        " - 'execute this script'\n"
        " - 'do this python file'\n"
        " - 'run X.py'\n"
        " - 'process this script'\n\n"
        "You MUST use the 'run_python_script' tool.\n\n"
        "You MUST output ONLY this JSON:\n\n"
        "{\n"
        "  \"action\": \"tool\",\n"
        "  \"tool_name\": \"run_python_script\",\n"
        "  \"args\": {\n"
        "    \"path\": \"<script_path>\",\n"
        "    \"args\": []\n"
        "  }\n"
        "}\n\n"
        "No plans.\n"
        "No codemods.\n"
        "No unified diffs.\n"
        "No explanations.\n"
        "No extra keys.\n"
        "No BOB_PLAN_SCHEMA.\n\n"
        "This is the ONLY correct output whenever the user requests script execution.\n"
    )

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
        first = raw.find("{")
        last = raw.rfind("}")
        if first != -1 and last != -1:
            raw = raw[first:last + 1]

        body = json.loads(raw)

        task_type = body.get("task_type", "analysis")
        summary = body.get("summary", "").strip() or user_text
        edits = body.get("edits") or []
        analysis_file = body.get("analysis_file") or ""
        tool_obj = body.get("tool") or {}
    except Exception as e:  # noqa: BLE001
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

    (queue_dir / f"{base}.plan.json").write_text(
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
        "original everywhere except the specific few lines that implement the requested change.\n"
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
            raw = raw[first:last + 1]

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
    except Exception as e:  # noqa: BLE001
        fallback = dict(base_task)
        fallback.setdefault(
            "summary",
            f"{base_task.get('summary', '')} (codemod refinement failed: {e!r})",
        )
        return fallback
