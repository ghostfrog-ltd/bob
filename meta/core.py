from __future__ import annotations

"""
meta/core.py — The full meta-layer for Bob ⇄ Chad

Responsibilities:
- Read recent task history
- Detect recurring failure patterns
- Generate self-improvement tickets
- Run tickets (snapshot → codemod → pytest → restore)
- Enqueue & run queue-based self-improvement tasks
- Teach Bob new planning rules
- Provide CLI tools (analyse, tickets, self_cycle, etc.)
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

# NOTE: meta_log intentionally stays inside bob/
from .log import log_history_record


logger = logging.getLogger("meta")

# ---------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]       # project root
DATA_DIR = ROOT_DIR / "data"
META_DIR = DATA_DIR / "meta"
HISTORY_FILE = META_DIR / "history.jsonl"
TICKETS_DIR = META_DIR / "tickets"
QUEUE_DIR = DATA_DIR / "queue"
TICKET_HISTORY_PATH = META_DIR / "tickets_history.jsonl"

SAFE_SELF_PATHS: Tuple[str, ...] = (
    "bob/config.py",
    "bob/planner.py",
    "bob/schema.py",
    "chad/notes.py",
    "meta/core.py",
)

META_TARGET_SELF = "self"
META_TARGET_GF = "ghostfrog"


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------

@dataclass
class HistoryRecord:
    ts: str
    target: str
    result: str
    tests: str | None = None
    error_summary: str | None = None
    human_fix_required: bool | None = None
    extra: Dict[str, Any] | None = None


@dataclass
class Issue:
    key: str
    area: str
    description: str
    evidence_ids: List[int]
    examples: List[str]


@dataclass
class Ticket:
    id: str
    scope: str
    area: str
    title: str
    description: str
    evidence: List[str]
    priority: str
    created_at: str
    safe_paths: List[str]
    raw_issue_key: str


# ---------------------------------------------------------------------
# Ticket fingerprinting and history
# ---------------------------------------------------------------------

def _append_ticket_history(
        fingerprint: str,
        status: str,
        extra: Dict[str, Any] | None = None,
) -> None:
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
        fingerprint: str, lookback_hours: int = 24
) -> bool:
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
    if isinstance(ticket, Ticket):
        component = ticket.area
        title = ticket.title
        summary = ticket.description
    else:
        component = ticket.get("area") or ticket.get("component") or ""
        title = ticket.get("title") or ""
        summary = ticket.get("description") or ticket.get("summary") or ""

    raw = json.dumps(
        {"component": component, "title": title, "summary": summary},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mark_ticket_failed(ticket: Ticket | Dict[str, Any], reason: str) -> None:
    fp = _ticket_fingerprint(ticket)
    _append_ticket_history(fp, "failed", {"reason": reason})


def mark_ticket_completed(ticket: Ticket | Dict[str, Any]) -> None:
    fp = _ticket_fingerprint(ticket)
    _append_ticket_history(fp, "completed")


# ---------------------------------------------------------------------
# Test runner + snapshot tools
# ---------------------------------------------------------------------

def _run_pytest(timeout: int = 300) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["pytest"], capture_output=True, text=True, timeout=timeout
        )
    except Exception as e:
        return False, f"pytest crashed: {e}"

    ok = proc.returncode == 0
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return ok, out


def _snapshot_files(rel_paths: List[str]) -> Dict[str, Optional[str]]:
    snap: Dict[str, Optional[str]] = {}
    for rel in rel_paths:
        p = ROOT_DIR / rel
        if not p.exists():
            snap[rel] = None
            continue
        if p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file():
                    rel_sub = sub.relative_to(ROOT_DIR).as_posix()
                    try:
                        snap[rel_sub] = sub.read_text(encoding="utf-8")
                    except Exception:
                        snap[rel_sub] = None
        else:
            try:
                snap[rel] = p.read_text(encoding="utf-8")
            except Exception:
                snap[rel] = None
    return snap


def _restore_files(snapshot: Dict[str, Optional[str]]) -> None:
    for rel, content in snapshot.items():
        p = ROOT_DIR / rel
        if content is None:
            if p.exists() and p.is_file():
                try: p.unlink()
                except Exception: pass
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------
# Run ticket with retries + pytest
# ---------------------------------------------------------------------

def run_ticket_with_tests(ticket: Ticket, max_attempts: int = 2) -> Dict[str, Any]:
    attempts = []
    success = False
    last_error = None

    for attempt in range(1, max_attempts + 1):
        snap = _snapshot_files(ticket.safe_paths)

        prompt = build_self_improvement_prompt(ticket)
        result = run_self_improvement_prompt(prompt, ticket)

        tests_ok, pytest_out = _run_pytest()
        tests_label = "pass" if tests_ok else "fail"

        # Log
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

        last_error = pytest_out
        _restore_files(snap)

    return {"success": success, "attempts": attempts, "last_error": last_error}


# ---------------------------------------------------------------------
# History loading, issue detection
# ---------------------------------------------------------------------

def load_history(limit: int = 200) -> List[HistoryRecord]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    out: List[HistoryRecord] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            HistoryRecord(
                ts=data.get("ts"),
                target=data.get("target") or "unknown",
                result=data.get("result") or "unknown",
                tests=data.get("tests"),
                error_summary=data.get("error_summary"),
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
                        "human_fix_required",
                    }
                }
                or None,
            )
        )
    return out


def _short_error_slug(error: str | None, max_len: int = 80) -> str:
    if not error:
        return "NO_ERROR"
    error = error.strip().replace("\n", " ")
    return error if len(error) <= max_len else error[: max_len - 3] + "..."


def _guess_area(rec: HistoryRecord) -> str:
    err = (rec.error_summary or "").lower()
    if "planner" in err or "plan" in err:
        return "planner"
    if "pytest" in err or "test" in err:
        return "tests"
    if "executor" in err:
        return "executor"
    return "other"


def detect_issues(history: Iterable[HistoryRecord]) -> List[Issue]:
    grouped: Dict[str, Issue] = {}

    for idx, rec in enumerate(history):
        if rec.result.lower() == "success":
            continue

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

    return sorted(grouped.values(), key=lambda i: len(i.evidence_ids), reverse=True)


# ---------------------------------------------------------------------
# Ticket creation
# ---------------------------------------------------------------------

def _priority_from_issue(issue: Issue) -> str:
    n = len(issue.evidence_ids)
    if n >= 10:
        return "high"
    if n >= 4:
        return "medium"
    return "low"


def _make_ticket_id(issue: Issue) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"T-{ts}-{abs(hash(issue.key)) % 100000:05d}"


def issues_to_tickets(
        issues: Iterable[Issue],
        scope: str = META_TARGET_SELF,
        limit: int = 5,
) -> List[Ticket]:
    out: List[Ticket] = []
    for issue in issues:
        if len(out) >= limit:
            break

        title = issue.description
        priority = _priority_from_issue(issue)
        created_at = datetime.now(tz=timezone.utc).isoformat()

        evidence_lines = [
            f"record #{idx}: {example}"
            for idx, example in zip(issue.evidence_ids, issue.examples)
        ]

        description = textwrap.dedent(
            f"""
            Area: {issue.area}
            Scope: {scope}

            Problem:
              {issue.description}

            Evidence:
            {chr(10).join("- " + e for e in evidence_lines) if evidence_lines else "(no examples)"}

            Desired outcome:
              Improve robustness in this area. Small, safe edits. All tests must pass.
            """
        ).strip()

        out.append(
            Ticket(
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
        )
    return out


def save_ticket(ticket: Ticket) -> Path:
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    path = TICKETS_DIR / f"{ticket.id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(ticket), f, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------------
# Self-improvement prompt
# ---------------------------------------------------------------------

def build_self_improvement_prompt(ticket: Ticket) -> str:
    return textwrap.dedent(
        f"""
        You are Bob running in SELF-IMPROVEMENT mode.

        Title: {ticket.title}
        Area: {ticket.area}
        Priority: {ticket.priority}

        Description:
        {ticket.description}

        You may edit ONLY these files:
        {chr(10).join("- " + p for p in ticket.safe_paths)}

        Goal:
          Make minimal, safe changes to fix this recurring issue.
          All pytest tests must pass.

        Constraints:
        - No new modules or files.
        - Keep diffs small.
        - Do not weaken jail or safety.
        - Prefer prompt changes, small heuristics, or shallow adjustments.
        """
    ).strip()


# ---------------------------------------------------------------------
# Core executor: Bob + Chad runner
# ---------------------------------------------------------------------

def run_self_improvement_prompt(prompt: str, ticket: Ticket) -> Dict[str, Any]:
    from app import bob_build_plan, chad_execute_plan, next_message_id

    id_str, date_str, base = next_message_id()
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    (QUEUE_DIR / f"{base}.user.txt").write_text(prompt, encoding="utf-8")

    plan = bob_build_plan(
        id_str=id_str,
        date_str=date_str,
        base=base,
        user_text=prompt,
        tools_enabled=True,
    )

    # enforce safe_paths
    task = plan.get("task") or {}
    edits = task.get("edits") or []
    if edits:
        allowed = set(ticket.safe_paths)
        filtered = []
        dropped = []
        for e in edits:
            rel = e.get("file")
            if rel in allowed:
                filtered.append(e)
            else:
                dropped.append(rel or "(none)")
        if dropped:
            print("[meta] Dropped edits:", dropped)
        task["edits"] = filtered
        plan["task"] = task

    exec_report = chad_execute_plan(
        id_str=id_str, date_str=date_str, base=base, plan=plan
    )

    msg = (exec_report.get("message") or "").lower()
    err = None
    result_label = "success"
    if "error" in msg or "failed" in msg:
        result_label = "fail"
        err = exec_report.get("message")

    # Log
    try:
        log_history_record(
            target=META_TARGET_SELF,
            result=result_label,
            tests="not_run",
            error_summary=err,
            human_fix_required=False,
            extra={
                "ticket_id": ticket.id,
                "task_type": (task.get("type") or "analysis"),
            },
        )
    except Exception:
        pass

    return {
        "plan": plan,
        "exec_report": exec_report,
        "result_label": result_label,
        "error_summary": err,
    }


# ---------------------------------------------------------------------
# Queue tools
# ---------------------------------------------------------------------

def enqueue_self_improvement(ticket: Ticket) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    prompt = build_self_improvement_prompt(ticket)

    item = {
        "kind": "self_improvement",
        "ticket_id": ticket.id,
        "scope": ticket.scope,
        "prompt": prompt,
        "safe_paths": ticket.safe_paths,
        "created_at": ticket.created_at,
    }

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = QUEUE_DIR / f"self_improvement_{ts}_{ticket.id}.json"
    path.write_text(json.dumps(item, indent=2), encoding="utf-8")
    return path


def _load_ticket_from_path(path: Path) -> Ticket:
    raw = json.loads(path.read_text(encoding="utf-8"))
    valid = {f.name for f in dataclass_fields(Ticket)}
    filtered = {k: v for k, v in raw.items() if k in valid}
    return Ticket(**filtered)


# ---------------------------------------------------------------------
# CLI Commands
# ---------------------------------------------------------------------

def cmd_analyse(args: argparse.Namespace) -> None:
    hist = load_history(limit=args.limit)
    issues = detect_issues(hist)
    if not issues:
        print("[meta] No issues detected.")
        return
    print(f"[meta] Found {len(issues)} recurring issues:")
    for issue in issues[: args.top]:
        print(f"- {issue.key!r}   area={issue.area}   occurrences={len(issue.evidence_ids)}")


def cmd_tickets(args: argparse.Namespace) -> None:
    hist = load_history(limit=args.limit)
    issues = detect_issues(hist)
    tickets = issues_to_tickets(issues, limit=args.count)
    if not tickets:
        print("[meta] No tickets generated.")
        return

    print(f"[meta] Generated {len(tickets)} ticket(s):")
    for t in tickets:
        path = save_ticket(t)
        print(f"- {t.id} -> {path}")


def cmd_self_improve(args: argparse.Namespace) -> None:
    hist = load_history(limit=args.limit)
    issues = detect_issues(hist)
    tickets = issues_to_tickets(issues, limit=args.count)
    if not tickets:
        print("[meta] No tickets generated.")
        return

    print("[meta] Enqueuing self improvement:")
    for t in tickets:
        save_ticket(t)
        q = enqueue_self_improvement(t)
        print(f"- {t.id} -> {q}")


def _filter_new_tickets(tickets: List[Ticket]) -> List[Ticket]:
    out = []
    for t in tickets:
        fp = _ticket_fingerprint(t)
        if _ticket_recently_completed(fp):
            print(f"[meta] Skipping duplicate ticket {t.title}")
            continue
        _append_ticket_history(fp, "created")
        out.append(t)
    return out


def cmd_self_cycle(args: argparse.Namespace) -> None:
    print("[meta] Running baseline tests...")
    ok, out = _run_pytest()
    if not ok:
        print("[meta] Baseline tests FAILED. Aborting self_cycle.")
        print(out[:400])
        return

    hist = load_history(limit=args.limit)
    issues = detect_issues(hist)
    raw = issues_to_tickets(issues, limit=args.count)
    tickets = _filter_new_tickets(raw)

    if not tickets:
        print("[meta] No tickets to run.")
        return

    print(f"[meta] Running {len(tickets)} tickets...")
    for t in tickets:
        save_ticket(t)
        summary = run_ticket_with_tests(t, max_attempts=args.retries)
        label = "OK" if summary["success"] else "FAILED"
        print(f"- {t.id} [{t.priority}] → {label}")


def cmd_new_ticket(args: argparse.Namespace) -> None:
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)

    title = args.title or "Manual ticket (edit me)"
    description = args.description or (
        "Manual ticket created via meta new_ticket.\nEdit title/desc/safe_paths/evidence."
    )

    now = datetime.now(tz=timezone.utc).isoformat()
    safe_paths = [p.strip() for p in args.paths] if args.paths else list(SAFE_SELF_PATHS)

    ticket_id = f"MANUAL-{uuid4().hex[:8]}"

    ticket = Ticket(
        id=ticket_id,
        scope=args.scope,
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
    print("[new_ticket] Created:")
    print(path)


def cmd_enqueue_ticket(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        print(f"[enqueue_ticket] File not found: {path}")
        return
    ticket = _load_ticket_from_path(path)
    q = enqueue_self_improvement(ticket)
    print("[enqueue_ticket] Enqueued:")
    print(q)


def cmd_run_queue(args: argparse.Namespace) -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    queue = sorted(QUEUE_DIR.glob("*.json"))
    if not queue:
        print("[run_queue] No queue items.")
        return

    items = []
    for qp in queue:
        try:
            raw = json.loads(qp.read_text())
        except:
            continue
        if raw.get("kind") == "self_improvement":
            items.append(qp)

    if not items:
        print("[run_queue] No self_improvement items.")
        return

    print(f"[run_queue] Found {len(items)} tasks...")

    for qp in items:
        raw = json.loads(qp.read_text())
        ticket_id = raw.get("ticket_id")

        ticket = None
        if ticket_id:
            tpath = TICKETS_DIR / f"{ticket_id}.json"
            if tpath.exists():
                try:
                    ticket = _load_ticket_from_path(tpath)
                except:
                    ticket = None

        if ticket is None:
            ticket = Ticket(
                id=ticket_id or f"Q-{uuid4().hex[:8]}",
                scope=raw.get("scope", META_TARGET_SELF),
                area="other",
                title=f"Queued self-improvement ({ticket_id})",
                description=(raw.get("prompt") or "")[:4000],
                evidence=["Queue item"],
                priority="medium",
                created_at=raw.get("created_at") or datetime.now(tz=timezone.utc).isoformat(),
                safe_paths=raw.get("safe_paths") or list(SAFE_SELF_PATHS),
                raw_issue_key=f"queue:{ticket_id}",
            )
            save_ticket(ticket)

        print(f"[run_queue] Running ticket {ticket.id}...")

        summary = run_ticket_with_tests(ticket, max_attempts=args.retries)
        label = "OK" if summary["success"] else "FAILED"
        print(f" → {label}")

        if summary["success"]:
            mark_ticket_completed(ticket)
            qp.rename(qp.with_suffix(".done.json"))
        else:
            mark_ticket_failed(ticket, summary.get("last_error") or "pytest failed")
            if args.keep_failed:
                qp.rename(qp.with_suffix(".failed.json"))
            else:
                qp.unlink()


# ---------------------------------------------------------------------
# CLI parser + entrypoint
# ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GhostFrog meta-layer")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyse")
    pa.add_argument("--limit", type=int, default=200)
    pa.add_argument("--top", type=int, default=10)
    pa.set_defaults(func=cmd_analyse)

    pt = sub.add_parser("tickets")
    pt.add_argument("--limit", type=int, default=200)
    pt.add_argument("--count", type=int, default=5)
    pt.set_defaults(func=cmd_tickets)

    ps = sub.add_parser("self_improve")
    ps.add_argument("--limit", type=int, default=200)
    ps.add_argument("--count", type=int, default=3)
    ps.set_defaults(func=cmd_self_improve)

    pc = sub.add_parser("self_cycle")
    pc.add_argument("--limit", type=int, default=200)
    pc.add_argument("--count", type=int, default=3)
    pc.add_argument("--retries", type=int, default=2)
    pc.set_defaults(func=cmd_self_cycle)

    pnt = sub.add_parser("new_ticket")
    pnt.add_argument("--title", default="")
    pnt.add_argument("--description", default="")
    pnt.add_argument("--area", default="other",
                     choices=["planner", "executor", "tests", "other"])
    pnt.add_argument("--priority", default="medium",
                     choices=["low", "medium", "high"])
    pnt.add_argument("--scope", default=META_TARGET_SELF)
    pnt.add_argument("--paths", nargs="*", default=[])
    pnt.set_defaults(func=cmd_new_ticket)

    pet = sub.add_parser("enqueue_ticket")
    pet.add_argument("--file", required=True)
    pet.set_defaults(func=cmd_enqueue_ticket)

    prq = sub.add_parser("run_queue")
    prq.add_argument("--retries", type=int, default=2)
    prq.add_argument("--keep-failed", action="store_true")
    prq.set_defaults(func=cmd_run_queue)

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
