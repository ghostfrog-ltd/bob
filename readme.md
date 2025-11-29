# Bob – Self-Improving Dev Assistant

Bob is the “thinking” layer of the GhostFrog dev environment: a planner that works with Chad (the executor) to read, modify, and improve a project inside a jailed directory.

High level:

- **Bob**: plans work (analysis, codemods, tools) and writes structured plans.
- **Chad**: executes those plans safely inside the project jail (runs tools, edits files, runs tests, sends emails, etc.).
- **Meta layer (`bob.meta`)**: watches history, generates “tickets” for self-improvement, and can auto-run those tickets through Bob/Chad.

The Flask UI at `/chat` is just the human front-end to this pipeline.

---

## Project layout (rough)

Some key bits you’ll touch:

- `app.py` – Flask UI + API for the Bob ↔ Chad message bus.
- `bob/` – Bob’s planning and meta layer:
  - `bob/plan.py` – core planning logic for tasks.
  - `bob/tools_registry.py` – registry of tools Chad can call.
  - `bob/meta.py` – meta layer (tickets, self-improvement, rules).
  - `bob/notes/` – rules and notes that guide Bob’s behaviour.
- `chad/` – execution layer:
  - `chad/executor.py` – runs plans using the tools registry.
- `helpers/` – shared utilities (jail resolver, text helpers, prompts, etc.).
- `data/`
  - `data/queue/` – incoming work items for Bob/Chad.
  - `data/scratch/` – temporary artefacts and analysis notes.
  - `data/meta/tickets/` – self-improvement tickets (JSON).

Exact structure may evolve, but the idea is: **Bob plans → Chad executes → meta watches and improves.**

---

## Getting started

### 1. Environment

Use Python 3.11+ if you can (but 3.10 is usually fine).

```bash
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate   # On Windows PowerShell

pip install -r requirements.txt
```

### 2. Run the chat UI

From the project root:

```bash
python3 app.py
```

Then open:

- http://127.0.0.1:8765/chat

This UI lets you:

- Send messages to Bob.
- See his plan.
- Watch Chad execute tools / codemods.
- View the final summary and snippets.

---

## Meta layer: Bob improving Bob/Chad

The meta layer (`bob.meta`) inspects recent history, generates self-improvement tickets, and can feed them back through the normal Bob/Chad pipeline.

> **Important:** All commands below assume you’re in the project root  
> and have your virtualenv activated.

### 1) Just inspect what the meta-layer sees

```bash
python3 -m bob.meta analyse --limit 200
```

### 2) Generate tickets only

```bash
python3 -m bob.meta tickets --count 5
```

### 3.a) Full flow: tickets + queue items for Bob/Chad

```bash
python3 -m bob.meta self_improve --count 3
```

### 3.b) One-shot: create tickets + Bob/Chad execute them

```bash
python3 -m bob.meta self_cycle --count 3
```

### 4) Teach Bob a rule

```bash
python3 -m bob.meta teach_rule ""
```

Example:

```bash
python3 -m bob.meta teach_rule "When planning self-improvement codemods, avoid planning edits for files that do not exist yet, unless you first create them with create_or_overwrite_file."
```

### 5) Repair and retry

```bash
python3 -m bob.meta repair_then_retry
```

### 6) Create a new ticket by hand

```bash
python3 -m bob.meta new_ticket \
  --title "Fix TOOL_REGISTRY drift" \
  --area planner \
  --priority medium \
  --paths bob/tools_registry.py bob/meta.py
```

---

## Typical workflows

### A. Normal dev work

```bash
python3 app.py
```

Then use `/chat`.

### B. Periodic self-improvement loop

```bash
python3 -m bob.meta analyse --limit 200
python3 -m bob.meta self_cycle --count 3
```

Teach new rules as needed.

---

## Notes / safety

- Project jail protects the filesystem.
- Tools registry defines what Chad can do.
- Tests catch regressions.
