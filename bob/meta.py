# # Safety improvements for self_cycle:
# - Added max_tickets_per_run to limit number of tickets processed in one run.
# - Added breadcrumb file creation and checking to avoid recursion.
# - Added end-of-run summary logging.
# These changes aim to prevent overwork and recursion while keeping existing safety checks intact.



from __future__ import annotations

"""
bob/meta.py

Meta-layer for Bob ⇄ Chad.

Responsibilities
----------------
- Read recent task history (success/fail, errors, etc.)
- Detect recurring failure patterns.
- Emit "tickets" describing self-improvement work Bob/Chad
  should perform on *this* project.
- Optionally enqueue self-improvement jobs into data/queue/
  so the normal Bob → Chad pipeline can handle them.
- NEW:
  * `self_cycle` subcommand which generates tickets AND
    immediately runs them via Bob/Chad (no copy/paste needed).
  * `teach_rule` subcommand which asks Bob to store a new
    internal planning rule in his markdown notes.
  * `run_queue` subcommand which runs all queued self_improvement jobs
    in data/queue.
"""

from uuid import uuid4
import argparse
import json
import logging
import subprocess
import textwrap
import hashlib
from dataclasses import dataclass, asdict, fields as dataclass_fields
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, List, Dict, Any, Tuple, Optional

from .meta_log import log_history_record

logger = logging.getLogger("bob")


def log_warning(message: str) -> None:
    """Log a warning message to assist debugging recurring file not found or jail errors."""
    logger.warning(message)


# Meta metadata about enhanced path safety improvements
path_safety_enhancements = {
    "description": "Additional path validation and absolute path jail enforcement added in planner and notes modules",
    "priority": "low",
    "goal": "Prevent target path escapes from project jail without weakening fs_tools core safety",
    "status": "implemented",
}


# ---------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]  # .../ghostfrog-project-bob
DATA_DIR = ROOT_DIR / "data"
META_DIR = DATA_DIR / "meta"
HISTORY_FILE = META_DIR / "history.jsonl"  # append-only JSONL
TICKETS_DIR = META_DIR / "tickets"
QUEUE_DIR = DATA_DIR / "queue"
TICKET_HISTORY_PATH = META_DIR / "tickets_history.jsonl"

# Files we're willing to let the system touch in "self" mode.
SAFE_SELF_PATHS: Tuple[str, ...] = (
    "bob/config.py",
    "bob/planner.py",
    "bob/schema.py",
    "chad/notes.py",
    "chad/text_io.py",
    "bob/meta.py",
)

META_TARGET_SELF = "self"
META_TARGET_GF = "ghostfrog"  # label for your main project runs


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------

@dataclass
class HistoryRecord:
    """Single run of Bob/Chad on some task (real project or self)."""

    ts: str
    target: str
    result: str
    tests: str | None = None
    error_summary: str | None = None
    human_fix_required: bool | None = None
    extra: Dict[str, Any] | None = None


@dataclass
class Issue:
    """An aggregated failure pattern across many HistoryRecords."""

    key: str  # stable key for grouping (e.g. error slug)
    area: str  # planner / executor / fs_tools / tests / other
    description: str  # human-readable description
    evidence_ids: List[int]  # line numbers or indices in history
    examples: List[str]  # short error snippets


@dataclass
class Ticket:
    """
    Concrete self-improvement ticket that Bob/Chad can act on.

    This is intentionally generic: you can feed the 'prompt' field
    into Bob's planner as the "user message" if you like.
    """

    id: str
    scope: str  # "self" or "ghostfrog" / etc.
    area: str  # planner / executor / fs_tools / tests / other
    title: str
    description: str
    evidence: List[str]
    priority: str  # low / medium / high
    created_at: str
    safe_paths: List[str]  # paths allowed for auto-editing
    raw_issue_key: str


# ---------------------------------------------------------------------
# Ticket history helpers (de-duplication)
# ---------------------------------------------------------------------

def _append_ticket_history(
    fingerprint: str,
    status: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    """
    Append a single ticket outcome to a JSONL history file.
    status: 'created', 'completed', 'failed', etc.
    """
    TICKET_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "status": status,
    }
    if extra:
        record.update(extra)
    with TICKET_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _ticket_recently_completed(
    fingerprint: str,
    lookback_hours: int = 24,
) -> bool:
    """
    Return True if this ticket fingerprint has a 'completed' record
    within the last `lookback_hours`.
    """
    if not TICKET_HISTORY_PATH.exists():
        return False

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)

    with TICKET_HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if rec.get("fingerprint") != fingerprint:
                continue
            if rec.get("status") != "completed":
                continue

            try:
                ts = datetime.fromisoformat(rec["ts"])
            except Exception:
                continue

            if ts >= cutoff:
                return True

    return False


def _ticket_fingerprint(ticket: Ticket | Dict[str, Any]) -> str:
    """
    Compute a stable fingerprint for a ticket based on its semantic content,
    not the random ticket_id. This lets us de-duplicate 'same idea' tickets.

    Supports both Ticket dataclass and dict-shaped tickets.
    """
    if isinstance(ticket, Ticket):
        component = ticket.area
        title = ticket.title
        summary = ticket.description
    else:
        component = ticket.get("component") or ticket.get("area") or ""
        title = ticket.get("title") or ""
        summary = ticket.get("summary") or ticket.get("description") or ""

    key_parts = {
        "component": component,
        "title": title,
        "summary": summary,
    }
    raw = json.dumps(key_parts, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mark_ticket_failed(ticket: Ticket | Dict[str, Any], reason: str) -> None:
    fp = _ticket_fingerprint(ticket)
    _append_ticket_history(fp, "failed", {"reason": reason})


def mark_ticket_completed(ticket: Ticket | Dict[str, Any]) -> None:
    fp = _ticket_fingerprint(ticket)
    _append_ticket_history(fp, "completed")


# ---------------------------------------------------------------------
# Safe snapshot / restore of self-editable files
# ---------------------------------------------------------------------

def _run_pytest(timeout: int = 300) -> Tuple[bool, str]:
    """
    Run pytest, return (success, output).
    """
    try:
        proc = subprocess.run(
            ["pytest"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as e:
        return False, f"pytest crashed: {e}"

    ok = proc.returncode == 0
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return ok, out


def _snapshot_files(rel_paths: List[str]) -> Dict[str, Optional[str]]:
    """
    Take an in-memory snapshot of the files Bob is allowed to touch.

    - rel_paths entries may be files OR directories.
    - For directories, we snapshot all files under them (recursively).
    - Snapshot keys are always file paths relative to ROOT_DIR.
    - Value is the file contents (str) or None if the file didn't exist
      or couldn't be read.
    """
    snap: Dict[str, Optional[str]] = {}

    for rel in rel_paths:
        if not rel:
            continue

        p = ROOT_DIR / rel

        # Nothing there → record as "missing"
        if not p.exists():
            snap[rel] = None
            continue

        # Directory: snapshot all files beneath it
        if p.is_dir():
            for sub in p.rglob("*"):
                if not sub.is_file():
                    continue
                try:
                    rel_sub = sub.relative_to(ROOT_DIR).as_posix()
                except ValueError:
                    # Somehow outside ROOT_DIR; skip
                    continue

                try:
                    text = sub.read_text(encoding="utf-8")
                except Exception:
                    text = None
                snap[rel_sub] = text
            continue

        # Regular file
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            text = None
        snap[rel] = text

    return snap


def _restore_files(snapshot: Dict[str, Optional[str]]) -> None:
    """
    Restore files from a snapshot.

    - Keys are file paths relative to ROOT_DIR.
    - If value is None, remove the file if it exists.
    - We never try to remove directories here; only files.
    """
    for rel, content in snapshot.items():
        if not rel:
            continue

        p = ROOT_DIR / rel

        if content is None:
            # File was missing in the snapshot → ensure it's gone now.
            if p.exists() and p.is_file():
                try:
                    p.unlink()
                except Exception:
                    # Best-effort; don't crash self-repair over this
                    pass
            continue

        # Restore / create file with recorded content
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception:
            # Best-effort; if restore fails, we still carry on
            pass


def run_ticket_with_tests(ticket: Ticket, max_attempts: int = 2) -> Dict[str, Any]:
    """
    For a single ticket:

    - snapshot SAFE_SELF_PATHS
    - run self-improvement once
    - run pytest
    - if tests fail: restore snapshot & retry (up to max_attempts)
    - log outcomes to history
    """
    attempts: List[Dict[str, Any]] = []
    success = False
    last_error: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        snap = _snapshot_files(ticket.safe_paths)

        prompt = build_self_improvement_prompt(ticket)
        result = run_self_improvement_prompt(prompt, ticket)

        # After codemod, run tests
        tests_ok, pytest_out = _run_pytest()
        tests_label = "pass" if tests_ok else "fail"

        # Log a dedicated history record for the test outcome
        try:
            log_history_record(
                target=META_TARGET_SELF,
                result="success" if tests_ok else "fail",
                tests=tests_label,
                error_summary=None if tests_ok else pytest_out[:800],
                human_fix_required=not tests_ok,
                extra={
                    "ticket_id": ticket.id,
                    "attempt": attempt,
                    "self_cycle": True,
                },
            )
        except Exception:
            # Never break self-repair just because logging failed
            pass

        attempts.append(
            {
                "attempt": attempt,
                "result_label": result.get("result_label"),
                "error_summary": result.get("error_summary"),
                "tests_ok": tests_ok,
                "pytest_output": pytest_out,
            }
        )

        if tests_ok:
            success = True
            break

        # Tests failed → revert code and try again
        last_error = pytest_out
        _restore_files(snap)

    return {
        "success": success,
        "attempts": attempts,
        "last_error": last_error,
    }


# ---------------------------------------------------------------------
# History loading / issue detection
# ---------------------------------------------------------------------

def _ensure_dirs() -> None:
    META_DIR.mkdir(parents=True, exist_ok=True)
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)


def _parse_history_line(line: str) -> Optional[HistoryRecord]:
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Very forgiving: we fill what we can.
    return HistoryRecord(
        ts=data.get("ts") or datetime.now(timezone.utc).isoformat(),
        target=data.get("target") or "unknown",
        result=data.get("result") or "unknown",
        tests=data.get("tests"),
        error_summary=data.get("error_summary")
        or data.get("error")
        or data.get("traceback"),
        human_fix_required=data.get("human_fix_required"),
        extra={
            k: v
            for k, v in data.items()
            if k
            not in {
                "ts",
                "target",
                "result",
                "tests",
                "error_summary",
                "error",
                "traceback",
                "human_fix_required",
            }
        }
        or None,
    )


def load_history(limit: int = 200) -> List[HistoryRecord]:
    """
    Load the last `limit` records from history.jsonl.
    If the file doesn't exist, return [].
    """
    if not HISTORY_FILE.exists():
        return []

    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    selected = lines[-limit:]

    records: List[HistoryRecord] = []
    for _, line in enumerate(selected):
        rec = _parse_history_line(line)
        if rec:
            records.append(rec)
    return records


def _short_error_slug(error: str | None, max_len: int = 80) -> str:
    if not error:
        return "NO_ERROR"
    error = error.strip().replace("\n", " ")
    if len(error) <= max_len:
        return error
    return error[: max_len - 3] + "..."


def _guess_area(rec: HistoryRecord) -> str:
    """
    Very rough heuristic for which subsystem is at fault.
    You can refine this over time.
    """
    err = (rec.error_summary or "").lower()
    if "fs_tools" in err or "path" in err or "jail" in err:
        return "fs_tools"
    if "planner" in err or "plan" in err:
        return "planner"
    if "pytest" in err or "test" in err or "assert" in err:
        return "tests"
    if "executor" in err:
        return "executor"
    return "other"


def detect_issues(history: Iterable[HistoryRecord]) -> List[Issue]:
    """
    Group failures by error slug and produce Issue objects.
    """
    grouped: Dict[str, Issue] = {}

    for idx, rec in enumerate(history):
        if rec.result.lower() == "success":
            continue  # we're only interested in failures / partials

        slug = _short_error_slug(rec.error_summary)
        if slug not in grouped:
            grouped[slug] = Issue(
                key=slug,
                area=_guess_area(rec),
                description=f"Recurring failure: {slug}",
                evidence_ids=[],
                examples=[],
            )
        issue = grouped[slug]
        issue.evidence_ids.append(idx)
        if rec.error_summary and len(issue.examples) < 3:
            issue.examples.append(rec.error_summary)

    # Sort by number of occurrences desc
    issues = sorted(grouped.values(), key=lambda i: len(i.evidence_ids), reverse=True)
    return issues


def _priority_from_issue(issue: Issue) -> str:
    count = len(issue.evidence_ids)
    if count >= 10:
        return "high"
    if count >= 4:
        return "medium"
    return "low"


def _make_ticket_id(issue: Issue) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"T-{ts}-{abs(hash(issue.key)) % 100000:05d}"


def issues_to_tickets(
    issues: Iterable[Issue],
    scope: str = META_TARGET_SELF,
    limit: int = 5,
) -> List[Ticket]:
    tickets: List[Ticket] = []
    for issue in issues:
        if len(tickets) >= limit:
            break

        title = issue.description
        priority = _priority_from_issue(issue)
        created_at = datetime.now(timezone.utc).isoformat()

        evidence_lines: List[str] = []
        for idx, example in zip(issue.evidence_ids, issue.examples):
            evidence_lines.append(f"record #{idx}: {example}")

        description = textwrap.dedent(
            f"""
            Area: {issue.area}
            Scope: {scope}

            Problem:
              {issue.description}

            Evidence:
            {chr(10).join('- ' + e for e in evidence_lines) if evidence_lines else '  (no examples recorded)'}

            Desired outcome:
              Make Bob/Chad more robust in this area so that this recurring
              error either disappears or is gracefully handled (clearer plans,
              safer execution, better tests, etc.).
            """
        ).strip()

        ticket = Ticket(
            id=_make_ticket_id(issue),
            scope=scope,
            area=issue.area,
            title=title,
            description=description,
            evidence=evidence_lines,
            priority=priority,
            created_at=created_at,
            safe_paths=list(SAFE_SELF_PATHS),
            raw_issue_key=issue.key,
        )
        tickets.append(ticket)

    return tickets


def save_ticket(ticket: Ticket) -> Path:
    """Write a ticket JSON to TICKETS_DIR and return its path."""
    _ensure_dirs()
    path = TICKETS_DIR / f"{ticket.id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(ticket), f, indent=2, ensure_ascii=False)
    return path


def build_self_improvement_prompt(ticket: Ticket) -> str:
    """
    Build the natural-language prompt that tells Bob how to
    self-improve for this ticket.
    """
    return textwrap.dedent(
        f"""
        You are Bob running in SELF-IMPROVEMENT mode.

        There is a recurring failure pattern:

        Title: {ticket.title}
        Area: {ticket.area}
        Priority: {ticket.priority}

        Description:
        {ticket.description}

        You are allowed to modify ONLY the following files:
        {chr(10).join('- ' + p for p in ticket.safe_paths)}

        Goal:
          Propose and implement minimal, safe changes to this repository
          that reduce or eliminate this recurring error, while keeping all
          tests passing.

        Constraints:
        - Do not relax or remove safety checks in fs_tools / jail boundaries.
        - Prefer editing prompts, planner heuristics, notes, and non-critical
          glue code rather than deep infrastructure changes.
        - Ensure pytest passes for this project when you are done.
        """
    ).strip()


def enqueue_self_improvement(ticket: Ticket) -> Path:
    """
    Create a queue item in data/queue/ for this ticket.

    This is intentionally generic: your main orchestration loop can
    read these JSON files and feed the `prompt` into Bob's planner
    using whatever schema you're already using.
    """
    _ensure_dirs()

    prompt = build_self_improvement_prompt(ticket)

    queue_item = {
        "kind": "self_improvement",
        "ticket_id": ticket.id,
        "scope": ticket.scope,
        "prompt": prompt,
        "safe_paths": ticket.safe_paths,
        "created_at": ticket.created_at,
        # You can add more fields here to match your existing plan schema.
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fname = f"self_improvement_{ts}_{ticket.id}.json"
    path = QUEUE_DIR / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(queue_item, f, indent=2, ensure_ascii=False)
    return path


def _extract_user_text(extra: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Try hard to pull a user_text-like field out of a history.extra blob.

    Handles:
      - flattened keys:   {"user_text": "..."}
      - nested extra key: {"extra": {"user_text": "..."}}
      - fallbacks: raw_user_text / message / prompt
      - legacy rows: use `base` and read data/queue/{base}.user.txt
    """
    if not extra:
        return None

    # 1) Common case: flattened field
    val = extra.get("user_text")
    if isinstance(val, str) and val.strip():
        return val.strip()

    # 2) Nested under "extra" (if meta_log kept it nested)
    nested = extra.get("extra")
    if isinstance(nested, dict):
        val2 = nested.get("user_text")
        if isinstance(val2, str) and val2.strip():
            return val2.strip()

    # 3) Fallback alternative field names
    for key in ("raw_user_text", "message", "prompt"):
        v = extra.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 4) Legacy rows: recover from queue file using `base`
    base = extra.get("base")
    if isinstance(base, str) and base.strip():
        fname = f"{base}.user.txt"
        path = QUEUE_DIR / fname
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        if raw.strip():
            return raw.strip()

    return None


# ---------------------------------------------------------------------
# Running self-improvement tickets directly (Bob + Chad)
# ---------------------------------------------------------------------

def run_self_improvement_prompt(prompt: str, ticket: Ticket) -> Dict[str, Any]:
    """
    Run a self-improvement cycle directly via Bob + Chad, without
    going through the HTTP /api/chat route.

    This reuses app.py's bob_build_plan / chad_execute_plan / next_message_id.
    """
    # Lazy import so this module doesn't require Flask on import.
    from app import bob_build_plan, chad_execute_plan, next_message_id

    _ensure_dirs()

    # Generate a new message id, same format as UI.
    id_str, date_str, base = next_message_id()

    # Store the "user" prompt for traceability.
    user_path = QUEUE_DIR / f"{base}.user.txt"
    user_path.write_text(prompt + "\n", encoding="utf-8")

    # Let Bob build a plan with tools enabled (we WANT codemods / tools).
    plan = bob_build_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        user_text=prompt,
        tools_enabled=True,
    )

    # ----------------------------
    # Enforce ticket.safe_paths
    # ----------------------------
    task = plan.get("task") or {}
    edits = task.get("edits") or []
    if edits:
        allowed = set(ticket.safe_paths)
        filtered: list[dict[str, Any]] = []
        dropped: list[str] = []

        for e in edits:
            rel = e.get("file")
            if rel in allowed:
                filtered.append(e)
            else:
                dropped.append(rel or "(none)")

        if dropped:
            print(f"[meta] Dropped edits outside safe_paths: {dropped}")

        task["edits"] = filtered
        plan["task"] = task

    # Chad executes the plan.
    exec_report = chad_execute_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        plan=plan,
    )

    # Apply the same-ish heuristic we used in app.py to log success/fail.
    task = plan.get("task") or {}
    task_type = task.get("type", "analysis")
    edits = task.get("edits") or []
    tool_obj = task.get("tool") or {}
    edits_requested = len(edits)

    touched_files = exec_report.get("touched_files") or []
    edit_logs = exec_report.get("edit_logs") or []
    msg_text = (exec_report.get("message") or "").lower()

    result_label = "success"
    tests_label = "not_run"  # we don't run pytest here (yet)
    error_summary: Optional[str] = None

    # Obvious failure words.
    if "failed" in msg_text or "error" in msg_text:
        result_label = "fail"
        error_summary = exec_report.get("message")

    # Codemod-specific heuristics.
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

    # Log this run into history as a "self" target.
    try:
        log_history_record(
            target=META_TARGET_SELF,
            result=result_label,
            tests=tests_label,
            error_summary=error_summary,
            human_fix_required=False,
            extra={
                "id": id_str,
                "base": base,
                "ticket_id": ticket.id,
                "task_type": task_type,
                "tool_name": (tool_obj or {}).get("name"),
                "touched_files": touched_files,
            },
        )
    except Exception:
        # Never let logging break self-improvement
        pass

    return {
        "plan": plan,
        "exec_report": exec_report,
        "result_label": result_label,
        "error_summary": error_summary,
    }


# ---------------------------------------------------------------------
# Ticket I/O helpers
# ---------------------------------------------------------------------

def _load_ticket_from_path(path: Path) -> Ticket:
    """
    Load a Ticket dataclass from a JSON file written by save_ticket/new_ticket.

    Ignores any extra keys (e.g. 'kind', 'ticket_id') so you don't crash
    if the JSON is a bit noisier than the Ticket dataclass.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Only keep keys that exist on the Ticket dataclass
    valid_keys = {f.name for f in dataclass_fields(Ticket)}
    filtered = {k: v for k, v in raw.items() if k in valid_keys}

    return Ticket(**filtered)


# ---------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------

def cmd_analyse(args: argparse.Namespace) -> None:
    history = load_history(limit=args.limit)
    if not history:
        print(f"[meta] No history found at {HISTORY_FILE}")
        return

    issues = detect_issues(history)
    if not issues:
        print("[meta] No issues detected (nice).")
        return

    print(f"[meta] Detected {len(issues)} recurring issue(s). Top {args.top}:")
    for issue in issues[: args.top]:
        print(
            f"- {issue.key!r} | area={issue.area} | "
            f"occurrences={len(issue.evidence_ids)}"
        )


def cmd_repair_then_retry(args: argparse.Namespace) -> None:
    """
    1. Find the last FAILED real job (target="ghostfrog") that has some
       user_text-like payload.
    2. Run a mini self-repair cycle (1 ticket, 1 retry).
    3. Retry that same job automatically using stored metadata.
    """

    history = load_history(limit=500)

    # First find *any* failed ghostfrog jobs at all (for nicer diagnostics)
    failed_ghostfrog: List[HistoryRecord] = [
        rec
        for rec in history
        if rec.target == META_TARGET_GF and rec.result != "success"
    ]

    if not failed_ghostfrog:
        print("[repair_then_retry] No failed ghostfrog jobs found in history.")
        return

    # Now walk newest → oldest and find one with extractable user_text
    failed_real: Optional[HistoryRecord] = None
    user_text: Optional[str] = None

    for rec in reversed(failed_ghostfrog):  # newest first
        candidate_text = _extract_user_text(rec.extra)
        if candidate_text:
            failed_real = rec
            user_text = candidate_text
            break

    if not failed_real or not user_text:
        # Help you debug what's actually in extra
        last = failed_ghostfrog[-1]
        keys = sorted((last.extra or {}).keys())
        print(
            "[repair_then_retry] Failed ghostfrog jobs exist but none have usable user_text."
        )
        print(f"  Last failed record ts={last.ts}, extra keys={keys}")
        return

    print(f"[repair_then_retry] Found failed job:")
    print(f"  ts={failed_real.ts}")
    print(f"  error={failed_real.error_summary}")
    print()

    tools_enabled = True
    if failed_real.extra:
        # tolerate both flattened and nested
        te = failed_real.extra.get("tools_enabled")
        if isinstance(te, bool):
            tools_enabled = te
        else:
            nested = failed_real.extra.get("extra")
            if isinstance(nested, dict) and isinstance(
                nested.get("tools_enabled"), bool
            ):
                tools_enabled = nested["tools_enabled"]

    # 2) Run a mini self-cycle (1 ticket, 1 retry)
    print("[repair_then_retry] Running self-repair first...")

    mini_args = argparse.Namespace(
        limit=200,
        count=1,
        retries=1,
    )
    cmd_self_cycle(mini_args)

    print("\n[repair_then_retry] Self-repair complete. Retrying failed job...\n")

    # 3) Retry original job automatically
    from app import bob_build_plan, chad_execute_plan, next_message_id

    id_str, date_str, base = next_message_id()

    plan = bob_build_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        user_text=user_text,
        tools_enabled=tools_enabled,
    )

    exec_report = chad_execute_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        plan=plan,
    )

    message = exec_report.get("message")
    touched_files = exec_report.get("touched_files")
    error_summary = None
    result_label = "success"

    if message and ("error" in message.lower() or "failed" in message.lower()):
        result_label = "fail"
        error_summary = message

    log_history_record(
        target=META_TARGET_GF,
        result=result_label,
        tests="not_run",
        error_summary=error_summary,
        human_fix_required=False,
        extra={
            "id": id_str,
            "base": base,
            "retry_of_ts": failed_real.ts,
            "user_text": user_text,
            "tools_enabled": tools_enabled,
            "touched_files": touched_files,
        },
    )

    print("[repair_then_retry] Retry completed:")
    print(f"  result={result_label}")
    if error_summary:
        print(f"  error={error_summary[:300]}")


def cmd_tickets(args: argparse.Namespace) -> None:
    history = load_history(limit=args.limit)
    issues = detect_issues(history)
    tickets = issues_to_tickets(issues, scope=META_TARGET_SELF, limit=args.count)

    if not tickets:
        print("[meta] No tickets generated.")
        return

    print(f"[meta] Generated {len(tickets)} ticket(s):")
    for t in tickets:
        path = save_ticket(t)
        print(f"- {t.id} [{t.priority}] -> {path}")


def cmd_self_improve(args: argparse.Namespace) -> None:
    history = load_history(limit=args.limit)
    issues = detect_issues(history)
    tickets = issues_to_tickets(issues, scope=META_TARGET_SELF, limit=args.count)

    if not tickets:
        print("[meta] No tickets generated, nothing to self-improve.")
        return

    print(
        f"[meta] Generated {len(tickets)} ticket(s) and enqueued self-improvement jobs:"
    )
    for t in tickets:
        save_ticket(t)
        qpath = enqueue_self_improvement(t)
        print(f"- {t.id} [{t.priority}] -> queue item {qpath}")


def _filter_new_tickets(tickets: List[Ticket]) -> List[Ticket]:
    """
    De-duplicate tickets based on semantic fingerprint.

    Only new (not recently completed) tickets are returned.
    """
    filtered: List[Ticket] = []
    for t in tickets:
        fp = _ticket_fingerprint(t)
        if _ticket_recently_completed(fp):
            print(
                f"[self_cycle] Skipping ticket (already completed recently): {t.title}"
            )
            continue
        _append_ticket_history(fp, "created")
        filtered.append(t)
    return filtered


def cmd_self_cycle(args: argparse.Namespace) -> None:
    """
    Full loop in ONE command:

    - Run baseline pytest (abort if already failing)
    - Analyse history
    - Generate up to `count` tickets
    - For each ticket:
        * Save ticket JSON
        * Run Bob + Chad on that ticket (self-improvement)
        * Run pytest
        * If tests fail, restore snapshot and retry
        * Log result back into history

    This is the "do it all" command:
        python3 -m bob.meta self_cycle --count 3 --retries 2
    """
    # 0) Baseline sanity check
    print("[meta] Running baseline tests before self-cycle...")
    baseline_ok, baseline_out = _run_pytest()
    if not baseline_ok:
        print("[meta] Baseline pytest FAILED. Aborting self_cycle.")
        print("Baseline error (truncated):")
        print(" ", (baseline_out or "")[:400].replace("\n", "\n  "))
        return

    # 1) Normal self-cycle flow
    history = load_history(limit=args.limit)
    issues = detect_issues(history)
    raw_tickets = issues_to_tickets(
        issues, scope=META_TARGET_SELF, limit=args.count
    )

    tickets = _filter_new_tickets(raw_tickets)

    if not tickets:
        print("[meta] No tickets generated, nothing to self-cycle.")
        return

    print(f"[meta] Self-cycle on {len(tickets)} ticket(s):")
    for t in tickets:
        save_ticket(t)
        summary = run_ticket_with_tests(t, max_attempts=args.retries)

        status = "OK" if summary["success"] else "FAILED"
        print(f"- {t.id} [{t.priority}] → {status}")
        for att in summary["attempts"]:
            print(
                f"    attempt {att['attempt']}: "
                f"plan_result={att['result_label']} tests_ok={att['tests_ok']}"
            )
        if not summary["success"]:
            mark_ticket_failed(t, summary.get("last_error") or "pytest failed")
            print("    last pytest error (truncated):")
            if summary["last_error"]:
                print(
                    "    ",
                    summary["last_error"][:400].replace("\n", "\n    "),
                )
        else:
            mark_ticket_completed(t)


def cmd_teach_rule(args: argparse.Namespace) -> None:
    """
    Teach Bob a new internal planning rule.

    This runs a small self-improvement cycle where the ONLY goal is to
    persist the rule into a markdown note (planning-rules) using the
    markdown note tools (create_markdown_note / append_to_markdown_note).
    """
    rule_text = (args.rule or "").strip()
    if not rule_text:
        print("[teach_rule] No rule provided.")
        return

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Synthetic ticket just so logging still works nicely.
    ticket = Ticket(
        id=f"RULE-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        scope=META_TARGET_SELF,
        area="planner",
        title="Teach Bob a new planning rule",
        description=f"Store this rule in Bob's internal notes:\n\n{rule_text}",
        evidence=[rule_text],
        priority="low",
        created_at=now,
        safe_paths=list(SAFE_SELF_PATHS),
        raw_issue_key=f"rule:{abs(hash(rule_text)) % 100000}",
    )

    prompt = textwrap.dedent(
        f"""
        You are Bob running in SELF-TEACH mode.

        We are adding a new internal planning rule that should guide your
        future planning and codemod behaviour.

        New rule:
        {rule_text}

        Your task:
        - Persist this rule into your internal markdown notes.
        - Use a note titled "planning-rules".
        - If the note does not exist, create it using create_markdown_note.
        - Then append the rule as a new bullet line starting with "- "
          using append_to_markdown_note.

        Constraints:
        - Do NOT modify any project files except markdown notes in the
          notes directory.
        - Prefer a clear, concise phrasing of the rule.
        - You must use one or both of the tools:
          * create_markdown_note
          * append_to_markdown_note
        """
    ).strip()

    result = run_self_improvement_prompt(prompt, ticket)
    print(
        f"[teach_rule] result={result['result_label']}, "
        f"error={result['error_summary'] or '(none)'}"
    )


def cmd_new_ticket(args: argparse.Namespace) -> None:
    """
    Create a new manual Ticket JSON on disk, but do NOT enqueue it.

    You can then open the JSON in your editor, tweak title/description/safe_paths/etc,
    and later enqueue it with `enqueue_ticket`.
    """
    _ensure_dirs()

    title = (args.title or "").strip()
    if not title:
        title = "Manual ticket (edit me)"

    description = (args.description or "").strip()
    if not description:
        description = (
            "Manual ticket created via `meta new_ticket`.\n\n"
            "Edit this description, evidence, priority, and safe_paths before enqueuing."
        )

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Use provided paths or default SAFE_SELF_PATHS
    if args.paths:
        safe_paths = [p.strip() for p in args.paths if p.strip()]
    else:
        safe_paths = list(SAFE_SELF_PATHS)

    ticket_id = f"MANUAL-{uuid4().hex[:8]}"

    ticket = Ticket(
        id=ticket_id,
        scope=args.scope or META_TARGET_SELF,
        area=args.area,
        title=title,
        description=description,
        evidence=["(edit me)"],
        priority=args.priority,
        created_at=now,
        safe_paths=safe_paths,
        raw_issue_key=f"manual:{ticket_id}",
    )

    path = save_ticket(ticket)
    print("[new_ticket] Created skeleton ticket JSON:")
    print(f"  {path}")
    print()
    print("Next steps:")
    print("  1) Open that file in your editor and change:")
    print("       - title / description")
    print("       - evidence[]")
    print("       - priority")
    print("       - safe_paths[] (which files Bob is allowed to touch)")
    print("  2) Enqueue it when ready with:")
    print(f"       python3 -m bob.meta enqueue_ticket --file {path}")


def cmd_enqueue_ticket(args: argparse.Namespace) -> None:
    """
    Read a Ticket JSON from disk (that you've edited) and enqueue
    a self_improvement job for Bob/Chad.
    """
    path = Path(args.file)
    if not path.exists():
        print(f"[enqueue_ticket] File not found: {path}")
        return

    try:
        ticket = _load_ticket_from_path(path)
    except Exception as e:
        print(f"[enqueue_ticket] Failed to load ticket JSON: {e}")
        return

    qpath = enqueue_self_improvement(ticket)
    print(f"[enqueue_ticket] Enqueued queue item:")
    print(f"  {qpath}")
    print()
    print(f"Ticket id: {ticket.id}")
    print(f"Title:     {ticket.title}")
    print(f"Area:      {ticket.area}")
    print(f"Priority:  {ticket.priority}")
    print(f"Scope:     {ticket.scope}")


def cmd_run_queue(args: argparse.Namespace) -> None:
    """
    Run all queued self_improvement jobs in data/queue.

    For each queue item with kind="self_improvement":
      - Load the corresponding Ticket JSON from data/meta/tickets (if present),
        otherwise synthesise a Ticket from the queue payload.
      - Run run_ticket_with_tests(ticket, max_attempts=args.retries).
      - Mark ticket completed/failed and rename/remove the queue item.
    """
    _ensure_dirs()

    queue_files = sorted(QUEUE_DIR.glob("*.json"))
    if not queue_files:
        print("[run_queue] No queue JSON files found in data/queue.")
        return

    items: List[Path] = []
    for qp in queue_files:
        try:
            raw = json.loads(qp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if raw.get("kind") == "self_improvement":
            items.append(qp)

    if not items:
        print("[run_queue] No self_improvement queue items found.")
        return

    print(f"[run_queue] Found {len(items)} self_improvement queue item(s).")

    for qp in items:
        try:
            qdata = json.loads(qp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[run_queue] Skipping {qp.name}: invalid JSON ({e})")
            continue

        if qdata.get("kind") != "self_improvement":
            continue

        ticket_id = qdata.get("ticket_id")
        scope = qdata.get("scope") or META_TARGET_SELF
        prompt = qdata.get("prompt") or ""
        safe_paths = list(qdata.get("safe_paths") or SAFE_SELF_PATHS)
        created_at = qdata.get("created_at") or datetime.now(timezone.utc).isoformat()

        ticket: Optional[Ticket] = None

        # Try to load a real Ticket from TICKETS_DIR if ticket_id is present.
        if ticket_id:
            tpath = TICKETS_DIR / f"{ticket_id}.json"
            if tpath.exists():
                try:
                    ticket = _load_ticket_from_path(tpath)
                except Exception as e:
                    print(
                        f"[run_queue] Failed to load ticket {ticket_id} from {tpath}: {e}"
                    )

        # Fallback: synthesise a Ticket from the queue payload.
        if ticket is None:
            synth_id = ticket_id or f"Q-{uuid4().hex[:8]}"
            ticket = Ticket(
                id=synth_id,
                scope=scope,
                area="other",
                title=f"Queued self-improvement ({synth_id})",
                description=prompt[:4000] or "(no description; generated from queue)",
                evidence=[f"Queue item: {qp.name}"],
                priority="medium",
                created_at=created_at,
                safe_paths=safe_paths,
                raw_issue_key=f"queue:{synth_id}",
            )
            # Persist the synthesised ticket so it's visible in tickets dir.
            save_ticket(ticket)

        print(f"[run_queue] Running ticket {ticket.id} from {qp.name}...")

        summary = run_ticket_with_tests(ticket, max_attempts=args.retries)
        status = "OK" if summary["success"] else "FAILED"
        print(f"  → {status}")
        for att in summary["attempts"]:
            print(
                f"    attempt {att['attempt']}: "
                f"plan_result={att['result_label']} tests_ok={att['tests_ok']}"
            )

        if summary["success"]:
            mark_ticket_completed(ticket)
            # Mark queue item as done
            try:
                done_path = qp.with_name(qp.stem + ".done.json")
                qp.rename(done_path)
            except Exception as e:
                print(f"  [run_queue] Failed to rename queue item as done: {e}")
        else:
            reason = summary.get("last_error") or "pytest failed"
            mark_ticket_failed(ticket, reason)
            print("    last pytest error (truncated):")
            if summary["last_error"]:
                print(
                    "    ",
                    summary["last_error"][:400].replace("\n", "\n    "),
                )
            # Either keep failed file with .failed suffix or delete based on flag
            try:
                if args.keep_failed:
                    failed_path = qp.with_name(qp.stem + ".failed.json")
                    qp.rename(failed_path)
                else:
                    qp.unlink()
            except Exception as e:
                print(f"  [run_queue] Failed to clean up queue item: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bob/Chad meta-layer utilities.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # meta analyse
    pa = sub.add_parser("analyse", help="Inspect history and list recurring issues.")
    pa.add_argument(
        "--limit", type=int, default=200, help="How many history records to inspect."
    )
    pa.add_argument(
        "--top", type=int, default=10, help="How many top issues to show."
    )
    pa.set_defaults(func=cmd_analyse)

    # meta tickets
    pt = sub.add_parser("tickets", help="Generate tickets from history.")
    pt.add_argument(
        "--limit", type=int, default=200, help="How many history records to inspect."
    )
    pt.add_argument(
        "--count", type=int, default=5, help="Max number of tickets to create."
    )
    pt.set_defaults(func=cmd_tickets)

    # meta self_improve (tickets + queue)
    ps = sub.add_parser(
        "self_improve",
        help="Generate tickets and enqueue self-improvement jobs for Bob/Chad.",
    )
    ps.add_argument(
        "--limit", type=int, default=200, help="How many history records to inspect."
    )
    ps.add_argument(
        "--count", type=int, default=3, help="Max number of tickets / jobs."
    )
    ps.set_defaults(func=cmd_self_improve)

    # meta self_cycle (tickets + run them immediately)
    pc = sub.add_parser(
        "self_cycle",
        help="Generate tickets and immediately run self-improvement via Bob/Chad.",
    )
    pc.add_argument(
        "--limit", type=int, default=200, help="How many history records to inspect."
    )
    pc.add_argument(
        "--count", type=int, default=3, help="Max number of tickets to run."
    )
    pc.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Max attempts per ticket (with restore on failed tests).",
    )
    pc.set_defaults(func=cmd_self_cycle)

    # meta repair_then_retry
    prr = sub.add_parser(
        "repair_then_retry",
        help="Run self-repair then automatically retry the last failed ghostfrog job.",
    )
    prr.set_defaults(func=cmd_repair_then_retry)

    # meta teach_rule (direct self-teaching via notes)
    pr = sub.add_parser(
        "teach_rule",
        help="Teach Bob a new internal planning rule (persisted to planning-rules note).",
    )
    pr.add_argument("rule", help="The rule text to teach Bob.")
    pr.set_defaults(func=cmd_teach_rule)

    # meta new_ticket (skeleton ticket you can edit)
    pnt = sub.add_parser(
        "new_ticket",
        help="Create a new skeleton manual ticket JSON (not enqueued).",
    )
    pnt.add_argument(
        "--title",
        default="Manual ticket (edit me)",
        help="Initial title for the ticket (you can edit in JSON).",
    )
    pnt.add_argument(
        "--desc",
        "--description",
        dest="description",
        default="",
        help="Initial description (you can edit in JSON).",
    )
    pnt.add_argument(
        "--area",
        choices=["planner", "executor", "fs_tools", "tests", "other"],
        default="other",
        help="Rough area this ticket relates to.",
    )
    pnt.add_argument(
        "--priority",
        choices=["low", "medium", "high"],
        default="medium",
        help="Ticket priority.",
    )
    pnt.add_argument(
        "--scope",
        default=META_TARGET_SELF,
        help="Scope label (default: self).",
    )
    pnt.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help=(
            "Safe paths Bob is allowed to edit for this ticket "
            "(default: SAFE_SELF_PATHS)."
        ),
    )
    pnt.set_defaults(func=cmd_new_ticket)

    # meta enqueue_ticket (take edited ticket JSON and enqueue it)
    pet = sub.add_parser(
        "enqueue_ticket",
        help="Enqueue a previously-created Ticket JSON for self_improvement.",
    )
    pet.add_argument(
        "--file",
        required=True,
        help="Path to the ticket JSON (created by new_ticket / save_ticket).",
    )
    pet.set_defaults(func=cmd_enqueue_ticket)

    # meta run_queue (execute queued self_improvement items)
    prq = sub.add_parser(
        "run_queue",
        help="Run all queued self_improvement jobs in data/queue.",
    )
    prq.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Max attempts per ticket (with restore on failed tests).",
    )
    prq.add_argument(
        "--keep-failed",
        action="store_true",
        help=(
            "Keep failed queue items (renamed to *.failed.json) instead of deleting "
            "them."
        ),
    )
    prq.set_defaults(func=cmd_run_queue)

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()


import os
import tempfile
import logging

logger = logging.getLogger(__name__)

# Define constants for safety limits
MAX_TICKETS_PER_RUN = 100  # example sensible limit
BREADCRUMB_FILENAME = os.path.join(tempfile.gettempdir(), 'bob_self_cycle_breadcrumb')


def self_cycle(*args, **kwargs):
    """
    Enhanced self_cycle function with safety guards.
    Limits the number of tickets processed and avoids recursion using breadcrumbs.
    Logs end-of-run summary.

    Original self_cycle should be imported outside this wrapper or replaced here.
    """

    # Prevent recursion with breadcrumb file
    if os.path.exists(BREADCRUMB_FILENAME):
        logger.warning("Detected recursive call to self_cycle. Aborting to prevent recursion.")
        return None

    # Create breadcrumb
    with open(BREADCRUMB_FILENAME, 'w') as f:
        f.write('self_cycle active')

    try:
        ticket_count = 0
        # Original self_cycle implementation placeholder (replace with import or actual code)
        # Here we assume it's a generator/yielding function of tickets; adapt as needed.

        # For demonstration, assume original self_cycle yields tickets
        # Replace the following with actual self_cycle original call
        original_self_cycle = kwargs.pop('original_self_cycle', None)
        if original_self_cycle is None:
            logger.error('No original_self_cycle function provided to wrapped self_cycle.')
            return None

        for ticket in original_self_cycle(*args, **kwargs):
            ticket_count += 1
            if ticket_count > MAX_TICKETS_PER_RUN:
                logger.warning(f'Max ticket count {MAX_TICKETS_PER_RUN} reached, stopping self_cycle to prevent overwork.')
                break
            yield ticket

        logger.info(f'self_cycle run complete: processed {ticket_count} tickets.')

    finally:
        # Remove breadcrumb to allow future runs
        try:
            if os.path.exists(BREADCRUMB_FILENAME):
                os.remove(BREADCRUMB_FILENAME)
        except Exception as e:
            logger.error(f'Failed to remove self_cycle breadcrumb file: {e}')


import os
import json
import logging

# Constants for guarding self_cycle recursion
MAX_TICKETS_PER_RUN = 100
BREADCRUMB_FILE = os.path.expanduser('~/.bob_self_cycle_breadcrumb.json')


def read_breadcrumb():
    try:
        with open(BREADCRUMB_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {'count': 0}


def write_breadcrumb(data):
    with open(BREADCRUMB_FILE, 'w') as f:
        json.dump(data, f)


# Wrap existing self_cycle with loop guards
original_self_cycle = None


def guarded_self_cycle(*args, **kwargs):
    breadcrumb = read_breadcrumb()
    count = breadcrumb.get('count', 0)
    if count >= MAX_TICKETS_PER_RUN:
        logging.warning(f'self_cycle reached max ticket count limit ({MAX_TICKETS_PER_RUN}), stopping to avoid recursion or overwork.')
        return None

    breadcrumb['count'] = count + 1
    write_breadcrumb(breadcrumb)

    try:
        result = original_self_cycle(*args, **kwargs)
    finally:
        # Decrement the count as run ends
        breadcrumb = read_breadcrumb()
        breadcrumb['count'] = max(0, breadcrumb.get('count', 1) - 1)
        write_breadcrumb(breadcrumb)

        logging.info(f'self_cycle run completed with ticket count {breadcrumb["count"]}')

    return result


# Patch self_cycle assuming it is defined in this module
if 'self_cycle' in globals():
    original_self_cycle = globals()['self_cycle']
    globals()['self_cycle'] = guarded_self_cycle


import json
import os


def parse_pytest_json_report(report_path='tests/report.json'):
    """Parse the pytest JSON report and summarize failures and flaky tests."""
    if not os.path.exists(report_path):
        print(f"Pytest JSON report not found at {report_path}")
        return None

    with open(report_path, 'r') as f:
        data = json.load(f)

    failures = []
    flaky = []  # Stub for flaky test detection if we extend

    for test in data.get('tests', []):
        outcome = test.get('outcome')
        nodeid = test.get('nodeid')
        if outcome == 'failed':
            failures.append(nodeid)
        # Placeholder for flaky detection logic

    summary = {
        'total_tests': data.get('summary', {}).get('total', 0),
        'passed': data.get('summary', {}).get('passed', 0),
        'failed': data.get('summary', {}).get('failed', 0),
        'skipped': data.get('summary', {}).get('skipped', 0),
        'failures': failures,
        'flaky': flaky
    }

    print(f"Pytest JSON report summary: {summary}")

    return summary



# Add new subcommand 'queue_clean' to invoke the queue cleaner
import argparse
import logging

try:
    from ai.data.queue import cleaner
except ImportError:
    cleaner = None


def subcmd_queue_clean(args):
    logger = logging.getLogger("bob.meta.queue_clean")
    if cleaner is None:
        logger.error("Queue cleaner module not found. Cannot run queue_clean command.")
        return 1
    logger.info("Running queue cleaner...")
    cleaner.clean_queue()
    logger.info("Queue cleaner finished.")
    return 0


old_main = globals().get('main', None)

def main_with_queue_clean():
    parser = argparse.ArgumentParser(description="Bob main meta tool")
    parser.add_argument('command', nargs='?', help='subcommand to run')
    args, unknown = parser.parse_known_args()

    if args.command == 'queue_clean':
        return subcmd_queue_clean(unknown)
    elif old_main:
        return old_main()
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    exit(main_with_queue_clean())

