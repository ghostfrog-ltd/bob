# bob/meta_web.py

from flask import Blueprint, render_template, abort, request, redirect, url_for
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import uuid4
import subprocess
from datetime import datetime, timezone

# Blueprint – mounted at /meta
meta_bp = Blueprint(
    "meta",
    __name__,
    url_prefix="/meta",
    template_folder="../meta",  # assumes project_root/templates/...
)

# Assume this file is in project_root/bob/meta_web.py
BASE_DIR = Path(__file__).resolve().parents[1]  # project root
TICKETS_DIR = BASE_DIR / "data" / "meta" / "tickets"


# ----------------- helpers -----------------

def generate_manual_ticket_id() -> str:
    """Generate a manual ticket_id like MANUAL-db3102a1."""
    return f"MANUAL-{uuid4().hex[:8]}"


def _load_ticket_file(path: Path) -> Dict[str, Any]:
    """Load a single ticket JSON file, tolerating errors and normalising fields."""
    try:
        with path.open("r", encoding="utf-8") as f:
            ticket = json.load(f)
    except Exception as e:
        ticket = {
            "ticket_id": path.stem,
            "title": f"[Failed to load: {e}]",
            "priority": "unknown",
            "status": "open",
        }

    # Ensure ticket_id exists
    ticket.setdefault("ticket_id", path.stem)

    # NORMALISATION LAYER for the UI:
    # - old schema uses: summary / acceptance_criteria
    # - real schema uses: description / evidence
    if "summary" not in ticket and "description" in ticket:
        ticket["summary"] = ticket["description"]

    if "acceptance_criteria" not in ticket and "evidence" in ticket:
        ticket["acceptance_criteria"] = ticket["evidence"]

    # And vice-versa (if a new ticket is created via UI with summary/acceptance_criteria)
    if "description" not in ticket and "summary" in ticket:
        ticket["description"] = ticket["summary"]

    if "evidence" not in ticket and "acceptance_criteria" in ticket:
        ticket["evidence"] = ticket["acceptance_criteria"]

    return ticket


def list_all_tickets() -> List[Dict[str, Any]]:
    """Return all ticket dicts sorted by ticket_id (desc)."""
    if not TICKETS_DIR.exists():
        return []

    tickets: List[Dict[str, Any]] = []
    for path in sorted(TICKETS_DIR.glob("*.json")):
        tickets.append(_load_ticket_file(path))

    # If ticket_id is date-based like 2025-11-28-10, this gives newest first
    tickets.sort(key=lambda t: t.get("ticket_id", ""), reverse=True)
    return tickets


def get_ticket_by_id(ticket_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a ticket by its ID.

    For now we assume filename is `{ticket_id}.json`.
    """
    candidate = TICKETS_DIR / f"{ticket_id}.json"
    if candidate.exists():
        return _load_ticket_file(candidate)

    # Fallback: scan all and match ticket_id field in case filenames differ
    for t in list_all_tickets():
        if t.get("ticket_id") == ticket_id:
            return t

    return None


# ----------------- routes -----------------


@meta_bp.route("/<ticket_id>/run", methods=["POST"])
def run_ticket(ticket_id: str):
    """
    Fire off Bob/Chad to work this specific ticket_id.

    This is fire-and-forget: we spawn a subprocess that runs
    `python3 -m bob.meta self_cycle --ticket-id <ticket_id> --count 1`.
    """
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        abort(404)

    # Don't run closed tickets
    if ticket.get("status") == "done":
        return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))

    # Optionally stamp a last_run_at field in the JSON
    ticket["last_run_at"] = datetime.now(timezone.utc).isoformat()
    path = TICKETS_DIR / f"{ticket_id}.json"
    if path.exists():
        with path.open("w", encoding="utf-8") as f:
            json.dump(ticket, f, indent=2)

    # Spawn Bob meta in the background
    # (BASE_DIR is your project root from earlier)
    try:
        subprocess.Popen(
            [
                "python3",
                "-m",
                "meta.core",
                "run_ticket",
                "--id",
                ticket_id,
                "--retries",
                "2",
            ],
            cwd=BASE_DIR,  # project root
        )
    except Exception as e:
        # You can log this properly if you want
        print(f"[meta_web] Failed to start self_cycle for {ticket_id}: {e}")

    return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))

@meta_bp.route("/<ticket_id>/edit", methods=["GET", "POST"])
def edit_ticket(ticket_id: str):
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        abort(404)

    # Helper to keep behaviour consistent with new_ticket()
    def _split_lines(block: str) -> list[str]:
        return [
            line.strip("-• ").strip()
            for line in block.splitlines()
            if line.strip()
        ]

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        area = (request.form.get("component") or "").strip()
        priority = (request.form.get("priority") or "medium").strip()
        summary = (request.form.get("summary") or "").strip()

        acceptance_raw = request.form.get("acceptance_criteria") or ""
        steps_raw = request.form.get("suggested_steps") or ""
        safe_paths_raw = request.form.get("safe_paths") or ""

        if not title:
            # Re-render form with error + posted data
            form = dict(request.form)
            form.setdefault("safe_paths", safe_paths_raw)
            return render_template(
                "meta_new.html",  # reuse same template
                error="Title is required.",
                form=form,
                ticket=ticket,
                edit_mode=True,
            )

        evidence = _split_lines(acceptance_raw)
        suggested_steps = _split_lines(steps_raw)
        safe_paths = [
            line.strip().lstrip("-• ").strip()
            for line in safe_paths_raw.splitlines()
            if line.strip()
        ]

        # Update fields on the existing ticket dict
        ticket["title"] = title
        ticket["area"] = area or ticket.get("area", "general")
        ticket["priority"] = priority
        ticket["description"] = summary or title
        ticket["summary"] = summary or title
        ticket["evidence"] = evidence
        ticket["acceptance_criteria"] = evidence
        ticket["suggested_steps"] = suggested_steps
        ticket["safe_paths"] = safe_paths

        # Keep id/ticket_id/created_at/kind/status as-is
        path = TICKETS_DIR / f"{ticket_id}.json"
        TICKETS_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(ticket, f, indent=2)

        return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))

    # GET: pre-populate form from existing ticket
    form = {
        "title": ticket.get("title", ""),
        "component": ticket.get("area", ""),
        "priority": ticket.get("priority", "medium"),
        "summary": ticket.get("summary") or ticket.get("description", ""),
        "acceptance_criteria": "\n".join(ticket.get("evidence") or []),
        "suggested_steps": "\n".join(ticket.get("suggested_steps") or []),
        "safe_paths": "\n".join(ticket.get("safe_paths") or []),
    }

    return render_template(
        "new.html",  # reuse same template
        error=None,
        form=form,
        ticket=ticket,
        edit_mode=True,
    )

@meta_bp.route("/new", methods=["GET", "POST"])
def new_ticket():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        area = (request.form.get("component") or "").strip()  # map component -> area
        priority = (request.form.get("priority") or "medium").strip()
        summary = (request.form.get("summary") or "").strip()

        acceptance_raw = request.form.get("acceptance_criteria") or ""
        steps_raw = request.form.get("suggested_steps") or ""

        if not title:
            return render_template(
                "meta_new.html",
                error="Title is required.",
                form=request.form,
            )

        def _split_lines(block: str) -> list[str]:
            return [
                line.strip("-• ").strip()
                for line in block.splitlines()
                if line.strip()
            ]

        evidence = _split_lines(acceptance_raw)

        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        # compact id like 2025-12-01-214215
        id_str = now.strftime("%Y-%m-%d-%H%M%S")
        ticket_id = generate_manual_ticket_id()
        raw_issue_key = f"manual:{id_str}"
        kind = (request.form.get("kind") or "self_improvement").strip()

        safe_paths_raw = request.form.get("safe_paths") or ""
        safe_paths = [
            line.strip().lstrip("-• ").strip()
            for line in safe_paths_raw.splitlines()
            if line.strip()
        ]

        ticket: Dict[str, Any] = {
            "id": id_str,
            "scope": "self",
            "area": area or "general",
            "title": title,
            "description": summary or title,
            "evidence": evidence,
            "priority": priority,
            "created_at": created_at,
            "safe_paths": safe_paths,
            "raw_issue_key": raw_issue_key,
            "ticket_id": ticket_id,
            "status": "open",
            "kind": kind,
            "summary": summary or title,
            "acceptance_criteria": evidence,
            "suggested_steps": _split_lines(steps_raw),
            "last_run": None,
            "last_bob_reply": None,
            "last_chad_summary": None,
        }

        TICKETS_DIR.mkdir(parents=True, exist_ok=True)
        path = TICKETS_DIR / f"{ticket_id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(ticket, f, indent=2)

        return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))

    # GET
    return render_template("new.html", error=None, form={})


@meta_bp.route("/")
def meta_index():
    """
    Index page listing meta tickets, with optional status filter.
    /meta?status=open | done | all
    """
    status = request.args.get("status", "open")  # default: open
    tickets = list_all_tickets()

    if status in {"open", "done"}:
        tickets = [
            t for t in tickets
            if (t.get("status") or "open") == status
        ]

    return render_template("index.html", tickets=tickets, current_status=status)


@meta_bp.route("/<ticket_id>")
def meta_detail(ticket_id: str):
    """Detail page for a single ticket."""
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        abort(404)
    return render_template("detail.html", ticket=ticket)


@meta_bp.route("/<ticket_id>/complete", methods=["POST"])
def mark_ticket_complete(ticket_id: str):
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        abort(404)

    # Update status
    ticket["status"] = "done"

    # Write updated JSON
    path = TICKETS_DIR / f"{ticket_id}.json"
    if path.exists():
        with path.open("w", encoding="utf-8") as f:
            json.dump(ticket, f, indent=2)

    return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))


@meta_bp.route("/<ticket_id>/reopen", methods=["POST"])
def reopen_ticket(ticket_id: str):
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        abort(404)

    ticket["status"] = "open"

    path = TICKETS_DIR / f"{ticket_id}.json"
    if path.exists():
        with path.open("w", encoding="utf-8") as f:
            json.dump(ticket, f, indent=2)

    return redirect(url_for("meta.meta_detail", ticket_id=ticket_id))
