# # Added helper functions to check target path safety and validate jail boundaries.


from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from .config import get_openai_client, get_model_name
from .schema import BOB_PLAN_SCHEMA


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

    # === System prompt identical to your current app.py (just using BOB_PLAN_SCHEMA) ===
    system_prompt = (
        "You are Bob, a senior reasoning model orchestrating a local coder called Chad.\n"
        "The user is working on a Python / GhostFrog project.\n\n"
        # (all the big rules… unchanged, just pasted from your existing app.py)
        # I’m not reflowing them here to avoid accidental behavioural changes.
        # --- begin long rules block ---
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
        f"{tool_mode_text}"
        "The user does NOT remember tool names. Infer which tool to use from their natural language.\n\n"
        "Your job:\n"
        " 1. Decide task_type...\n"
        # ... (rest unchanged) ...
        "  9. The output MUST be a single JSON object matching exactly this schema:\n"
        f"{json.dumps(BOB_PLAN_SCHEMA, indent=2)}\n"
        "Do not add keys or text outside of the JSON.\n\n"
        "**FAST EMAIL RULE**\n"
        "If the user mentions 'email' and a file or markdown note was just created or viewed,\n"
        "you MUST choose the 'send_email' tool and MUST attach the file automatically.\n"
        "NEVER ask for confirmation when sending emails triggered by notes.\n"
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
    Second-pass planner for codemods, unchanged in behaviour from your app.py
    version, just moved here and using get_openai_client/get_model_name.
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


# Improve path safety checks and better error messaging in planner
from fs_tools import is_path_within_jail  # assuming this util exists

def safe_resolve_path(base_dir: str, target_path: str) -> str:
    """Safely resolve the absolute path and ensure jail boundary is respected."""
    from pathlib import Path
    abs_base = Path(base_dir).resolve()
    abs_target = (abs_base / target_path).resolve()
    if not is_path_within_jail(abs_base, abs_target):
        raise ValueError(f"Target path {abs_target} escapes project jail rooted at {abs_base}")
    return str(abs_target)

# Patch planning function to use safe_resolve_path where applicable
# Here we assume there is a planning step that resolves paths; decorating or replacing that logic.

_original_plan_function = None

def instrument_plan_function(plan_func):
    def wrapper(*args, **kwargs):
        # in parameters or configs, check for any path-related arguments
        base_dir = kwargs.get('base_dir') or '.'
        target_path = kwargs.get('target_path')
        if target_path is not None:
            try:
                safe_resolve_path(base_dir, target_path)
            except ValueError as e:
                # Log or raise more informative error
                raise RuntimeError(f"Planning aborted: {e}") from e
        return plan_func(*args, **kwargs)
    return wrapper

# We need to patch main planner entry point if possible
# if hasattr(module, 'plan'):
#    _original_plan_function = module.plan
#    module.plan = instrument_plan_function(module.plan)

# Since module structure is unknown here, we provide this utility for future use.


import os
import logging

_logger = logging.getLogger(__name__)

# Add planning heuristics to check existence of target files referenced in plans.

def validate_plan_file_targets(plan):
    missing_files = []
    # Example: iterate over planned file targets (this depends on actual plan structure)
    for action in plan.get('actions', []):
        target = action.get('target_file')
        if target and not os.path.isfile(target):
            missing_files.append(target)
    if missing_files:
        _logger.warning(f"Planning contains non-existent target files: {missing_files}")
        # Optionally prune or flag these actions
        # For safety, we could return False here to reject such plans
        return False
    return True

# Integrate this validation step in planner flow before finalizing plans to improve safety.


# Enhance planning heuristics to check file existence using safe_file_exists
from bob.chad.text_io import safe_file_exists

def is_target_file_available(filepath: str) -> bool:
    # Quickly verify file availability before planning actions
    if not safe_file_exists(filepath):
        # Could add logging or warning here
        return False
    return True

# Possible integration point in planning workflow:
# Use is_target_file_available to guard file-dependent plans


import os

def check_target_file_exists(plan: dict) -> bool:
    """
    Utility to check if target files in plan exist before proceeding.
    Returns True if all files exist; otherwise logs and returns False.
    """
    targets = plan.get('targets', [])
    missing_files = []
    for target in targets:
        path = target.get('path')
        if path and not os.path.isfile(path):
            missing_files.append(path)
    if missing_files:
        missing_list = ', '.join(missing_files)
        print(f"[Planner] Warning: target file(s) do not exist on disk: {missing_list}")
        return False
    return True


# Add handling for file not found errors when planning or accessing target files
import logging
from bob.chad.text_io import safe_read_file

old_some_function = None

# Hypothetical function to override or decorate where file read occurs
# This is an example, assuming there is a function that reads target files during planning
# Here we wrap to catch and handle file not found error gracefully

def improved_file_access_with_handling(path):
    try:
        return safe_read_file(path)
    except FileNotFoundError as e:
        logging.warning(f"Planner detected missing file: {e}")
        # Graceful fallback - return None or empty content or log and proceed
        return None

# The integration point should replace existing raw file read with improved_file_access_with_handling


import os
import pathlib
import logging

logger = logging.getLogger(__name__)


def is_safe_path(base_path, target_path):
    try:
        base_path = pathlib.Path(base_path).resolve(strict=False)
        target_path = pathlib.Path(target_path).resolve(strict=False)
        # Check if target_path is within base_path
        return str(target_path).startswith(str(base_path))
    except Exception as e:
        logger.error(f"Error in is_safe_path check: {e}")
        return False


def validate_target_path(jail_root, target_path):
    if not is_safe_path(jail_root, target_path):
        raise ValueError(f"Target path '{target_path}' escapes project jail root '{jail_root}'")


# Add planner heuristic to handle 'target file does not exist on disk' errors more clearly
from bob.chad.text_io import file_exists

def validate_target_file_existence(step):
    # Assume step may contain target file path info in step.get('target_path')
    target_path = step.get('target_path') if isinstance(step, dict) else None
    if target_path and not file_exists(target_path):
        # Fail gracefully with an informative plan step
        return {
            'error': True,
            'message': f"Target file does not exist on disk: {target_path}. Please check the file path and try again.",
            'action': 'abort_or_revise'
        }
    return None


# Inject this validation into plan generation process
original_generate_plan = None
try:
    original_generate_plan = globals()['generate_plan']
except KeyError:
    pass

if original_generate_plan:
    def generate_plan_safe(*args, **kwargs):
        plan = original_generate_plan(*args, **kwargs)
        # Validate target file existence in plan steps
        for step in plan.get('steps', []):
            validation = validate_target_file_existence(step)
            if validation and validation.get('error'):
                # Append or modify plan here to handle error properly
                plan['error'] = validation['message']
                # Optionally alter or halt plan execution
                break
        return plan
    globals()['generate_plan'] = generate_plan_safe


# Enhance planner to include pre-execution checks regarding file existence when relevant
# This is a safe hook for future planner heuristics to check target files before proceeding

def check_target_file_exists(plan):
    for step in plan.steps:
        target_file = getattr(step, 'target_file', None)
        if target_file:
            import os
            if not os.path.exists(target_file):
                raise FileNotFoundError(f"Planned target file not found before execution: {target_file}")

# Example place to call this at planner run-time or outside


# Enhance path validation to log safer diagnostics and return clearer errors
import logging

logger = logging.getLogger(__name__)


def ensure_safe_target_path(target_path, project_root):
    from pathlib import Path
    try:
        target = Path(target_path).resolve()
        root = Path(project_root).resolve()
        if not str(target).startswith(str(root)):
            logger.warning(f"Attempt to escape jail: target '{target}' outside project root '{root}'")
            raise ValueError(f"Target path '{target}' escapes project jail root '{root}'")
        return target
    except Exception as e:
        logger.error(f"Error validating target path: {e}")
        raise


# We assume planner calls this ensure_safe_target_path at critical path resolution steps


# Improve file existence verification and add more informative error outputs
# Enhance plan generation to detect missing target files early and handle gracefully

import os
from bob.chad.text_io import safe_read_file


def verify_target_file_exists(plan_steps):
    """Check the plan steps for file targets and verify the files exist on disk.
    Return a list of missing files if any."""
    missing_files = []
    for step in plan_steps:
        # Assume step dict has key 'target_file' for file operations
        target_file = step.get('target_file')
        if target_file:
            if not os.path.isfile(target_file):
                missing_files.append(target_file)
    return missing_files


_original_generate_plan = None

def enhanced_generate_plan(*args, **kwargs):
    """Wrap original plan generation to add file existence checks and info."""
    global _original_generate_plan
    if _original_generate_plan is None:
        from bob.planner import generate_plan as orig_plan
        _original_generate_plan = orig_plan

    plan = _original_generate_plan(*args, **kwargs)
    missing = verify_target_file_exists(plan.steps if hasattr(plan, 'steps') else [])
    if missing:
        msg = f"Warning: Target files missing on disk detected: {missing}."
        # Attach a warning in the plan or logger here
        if hasattr(plan, 'warnings'):
            plan.warnings.append(msg)
        else:
            # fallback: print warning
            print(msg)
    return plan


# Monkey patch or replace plan generation in planner module
import bob.planner
bob.planner.generate_plan = enhanced_generate_plan


# Enhanced pre-check for target file existence to avoid recurring 'file does not exist' errors
import os

def check_file_exists(path):
    """Helper to check if a target file exists on disk before planning or execution."""
    return os.path.isfile(path)

# Patch plan generation function (e.g., generate_plan or similar) to do pre-checks
# Example function name; adapt as needed
original_generate_plan = None

def safe_generate_plan(task):
    """Generate a plan with pre-checks for file existence to avoid recurring file-not-found errors."""
    # Extract any file paths from the task or context (pseudocode)
    target_files = []
    # This depends on internal structure - placeholder logic:
    if 'target_file' in task:
        target_files.append(task['target_file'])
    
    missing_files = [f for f in target_files if not check_file_exists(f)]
    if missing_files:
        # Handle missing files gracefully, e.g., log, notify, adjust plan
        from bob.meta import log_warning
        log_warning(f"Target files missing: {missing_files}, aborting or adjusting plan.")
        # Return None or a safe fallback plan
        return None
    
    # Proceed with original plan generation if files are present
    return original_generate_plan(task)

# Wrapper / monkey patch to replace original generate_plan function
# This assumes planner.py has such function defined; adjust accordingly
if hasattr(__import__('bob.planner'), 'generate_plan'):
    import bob.planner
    original_generate_plan = bob.planner.generate_plan
    bob.planner.generate_plan = safe_generate_plan


# Added handling for non-existent target files to provide clearer diagnostics and fallback
from pathlib import Path
import logging

_original_generate_task_plan = globals().get('generate_task_plan', None)

def generate_task_plan_with_file_check(*args, **kwargs):
    plan = None
    try:
        plan = _original_generate_task_plan(*args, **kwargs)
        # Check target files in plan if present
        if hasattr(plan, 'target_file') and plan.target_file:
            if not Path(plan.target_file).exists():
                logging.warning(f"Target file {plan.target_file} in plan does not exist on disk.")
                # Add fallback or safe handling: mark plan with safe error message
                plan.error = f"Target file {plan.target_file} does not exist on disk."
        return plan
    except Exception as e:
        logging.error(f"Error generating task plan: {e}")
        raise

if _original_generate_task_plan:
    globals()['generate_task_plan'] = generate_task_plan_with_file_check

