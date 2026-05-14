# HR Recruiting Agent

AI-powered recruiting pipeline built with LangGraph + FastAPI. Automates CV scoring, parallel approvals (HM / CFO / Legal), interview scheduling, and offer flow — with human-in-the-loop interrupts at every step.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- OpenAI API key

---

## Installation

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd hr-test-assignement

# 2. Install dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# Open .env and set your key:
# OPENAI_API_KEY=sk-...

# 4. Seed the database (creates SQLite DB + sample data)
uv run python -m src.db
```

---

## Run

```bash
uv run uvicorn src.app:app --reload --port 8000
```

Open in browser: **http://localhost:8000**

---

## Walkthrough: full pipeline test

### Step 1 — Submit a CV (as candidate)

1. Switch role to **candidate** (top-right role switcher)
2. Scroll to **Apply for a Job** form
3. Paste one of the sample CVs from `data/sample_cvs/`:
   - `alice_johnson.txt` — strong candidate (should pass)
   - `bob_smith.txt` — weak candidate (likely rejected early)
   - `carol_no_email.txt` — no email (tests the no-contact branch)
4. Select the job, click **Submit**
5. You are redirected to the candidate page — AI parses CV and scores it automatically

### Step 2 — Recruiter review

1. Switch role to **recruiter**
2. Dashboard shows a pending action for the candidate
3. Click **Approve** (or **Reject** to end the flow here)

### Step 3 — Parallel approvals (HM / CFO / Legal)

After recruiter approval, three approvals run in parallel.

1. Switch role to **hm** → approve
2. Switch role to **cfo** → approve
3. Switch role to **legal** → approve

Any one rejection ends the pipeline.

### Step 4 — Interview

1. Switch role to **candidate** → accept the interview invitation
2. Switch role to **interviewer** → submit scorecard (approve/reject)

### Step 5 — Offer

1. Switch role to **recruiter** → review and approve the AI-generated offer
2. Switch role to **candidate** → accept or reject the offer
3. Status changes to **hired**

### Other pages

| URL | What it shows |
|-----|--------------|
| `/candidate/{id}` | Full timeline, workflow state, pending actions |
| `/inbox` | Messages for the current role (emails, Slack) |
| `/logs` | Audit trail + all sent emails and Slack messages |

### Simulating time

Use the **Skip Time** button on the dashboard to advance virtual days. After 3 days of inactivity, pending actors receive a Slack nudge automatically.

---

## Visualize the LangGraph

### Option 1 — Print ASCII graph in terminal

```bash
uv run python -c "
from src.workflow import build_graph
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3, io

builder = build_graph()
graph = builder.compile(checkpointer=SqliteSaver(sqlite3.connect(':memory:')))
print(graph.get_graph().draw_ascii())
"
```

### Option 2 — Export as PNG (requires `pygraphviz` or `Pillow`)

```bash
uv run pip install pygraphviz  # or: uv add pygraphviz

uv run python -c "
from src.workflow import build_graph
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

builder = build_graph()
graph = builder.compile(checkpointer=SqliteSaver(sqlite3.connect(':memory:')))
img = graph.get_graph().draw_mermaid_png()
open('graph.png', 'wb').write(img)
print('Saved: graph.png')
"
```

Open `graph.png` to see the full node/edge diagram.

### Option 3 — Mermaid diagram (paste into any viewer)

```bash
uv run python -c "
from src.workflow import build_graph
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

builder = build_graph()
graph = builder.compile(checkpointer=SqliteSaver(sqlite3.connect(':memory:')))
print(graph.get_graph().draw_mermaid())
"
```

Paste the output into [mermaid.live](https://mermaid.live) to view interactively.

### Option 4 — LangGraph Studio (official browser UI)

Current official approach — `langgraph dev` command opens Studio in browser.

```bash
uv run langgraph dev
```

Opens at **http://localhost:2024** — interactive graph, step-through execution, state diffs at each node, interrupt points highlighted visually.

`langgraph.json` is already configured in the project root. Studio uses an in-memory checkpointer (isolated from the main app's SQLite state).

---

## Project structure

```
src/
  app.py        — FastAPI routes
  workflow.py   — LangGraph graph definition, checkpointer, start/resume
  nodes.py      — Node functions (each step of the pipeline)
  llm.py        — OpenAI calls (CV scoring, offer generation, etc.)
  models.py     — SQLModel DB models
  comms.py      — Email / Slack simulation + audit log
  db.py         — DB init and seed
data/
  hr.db         — SQLite (candidates, jobs, messages)
  checkpoints.db — LangGraph state checkpoints
  sample_cvs/   — Test CVs
logs/
  audit.jsonl   — All events
  emails/       — Sent emails (markdown files)
  slack/        — Sent Slack messages (markdown files)
```

---

## Running tests

```bash
uv run pytest
```
