"""FastAPI application — routes for HR recruiting agent UI."""

from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from src import clock as vclock
from src import comms, workflow
from src.db import get_session, init_db
from src.models import AuditEvent, Candidate, Job, Message

app = FastAPI(title="HR Recruiting Agent")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ROLES = ["candidate", "recruiter", "hm", "cfo", "legal", "interviewer"]
STAGE_ORDER = ["intake", "screening", "approvals", "interview", "offer", "hired", "rejected"]


@app.on_event("startup")
def startup():
    init_db()


def _render(name: str, request: Request, session: Session, **extra):
    role = request.cookies.get("role", "recruiter")
    focus_id = request.cookies.get("focus_candidate_id", "")
    day = vclock.now(session)
    candidates = list(session.exec(select(Candidate).where(Candidate.status == "active")))
    ctx = {
        "request": request,
        "role": role,
        "roles": ROLES,
        "day": day,
        "focus_candidate_id": int(focus_id) if focus_id else None,
        "active_candidates": candidates,
        **extra,
    }
    return templates.TemplateResponse(request=request, name=name, context=ctx)


# ── Role switcher ────────────────────────────────────────────────
@app.post("/set-role")
def set_role(role: str = Form(...)):
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie("role", role)
    return resp


# ── Skip time ────────────────────────────────────────────────────
@app.post("/skip-time")
def skip_time(days: int = Form(1), session: Session = Depends(get_session)):
    new_day = vclock.advance(session, days)
    _check_nudges(session, new_day)
    return RedirectResponse(url="/", status_code=303)


def _check_nudges(session: Session, current_day: int):
    candidates = session.exec(select(Candidate).where(Candidate.status == "active")).all()
    for c in candidates:
        if not c.thread_id:
            continue
        ws = workflow.get_workflow_state(c.thread_id)
        if not ws or not ws["next"]:
            continue
        last_action = ws["values"].get("last_action_day", 0)
        if current_day - last_action >= 3:
            for node in ws["next"]:
                role = _node_to_role(node)
                comms.send_slack(
                    session, c.id, "nudge", role,
                    f"⏰ Reminder: {c.name} is waiting for your action ({node}) for {current_day - last_action} days.",
                )


def _node_to_role(node: str) -> str:
    mapping = {
        "recruiter_review": "recruiter",
        "approval_hm": "hm",
        "approval_cfo": "cfo",
        "approval_legal": "legal",
        "interview_schedule": "candidate",
        "interview_scorecard": "interviewer",
        "offer_recruiter_review": "recruiter",
        "offer_candidate_decision": "candidate",
    }
    return mapping.get(node, "recruiter")


# ── Dashboard ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    role = request.cookies.get("role", "recruiter")
    candidates = list(session.exec(select(Candidate).order_by(Candidate.id.desc())))
    jobs = list(session.exec(select(Job)))

    pending_actions = []
    for c in candidates:
        if c.status != "active" or not c.thread_id:
            continue
        ws = workflow.get_workflow_state(c.thread_id)
        if not ws:
            continue
        for intr in ws.get("interrupts", []):
            if _node_to_role(intr["node"]) == role:
                pending_actions.append({"candidate": c, "node": intr["node"], "state": ws["values"]})
        if not ws.get("interrupts") and ws.get("next"):
            for node in ws["next"]:
                if _node_to_role(node) == role:
                    pending_actions.append({"candidate": c, "node": node, "state": ws["values"]})

    return _render("dashboard.html", request, session,
                   candidates=candidates, jobs=jobs, pending_actions=pending_actions)


# ── Candidate detail ─────────────────────────────────────────────
@app.get("/candidate/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(candidate_id: int, request: Request, session: Session = Depends(get_session)):
    candidate = session.get(Candidate, candidate_id)
    if not candidate:
        return RedirectResponse(url="/", status_code=303)

    events = list(session.exec(
        select(AuditEvent).where(AuditEvent.candidate_id == candidate_id).order_by(AuditEvent.id)
    ))

    ws = None
    pending_nodes = []
    interrupts = []
    if candidate.thread_id:
        ws = workflow.get_workflow_state(candidate.thread_id)
        if ws:
            pending_nodes = ws.get("next", [])
            interrupts = ws.get("interrupts", [])

    resp = _render("candidate.html", request, session,
                   candidate=candidate, events=events, workflow_state=ws,
                   pending_nodes=pending_nodes, interrupts=interrupts)
    resp.set_cookie("focus_candidate_id", str(candidate_id))
    return resp


# ── Apply (candidate submits CV) ─────────────────────────────────
@app.post("/apply")
def apply(cv_text: str = Form(...), job_id: int = Form(...), session: Session = Depends(get_session)):
    import uuid

    thread_id = str(uuid.uuid4())
    candidate = Candidate(cv_text=cv_text, job_id=job_id, thread_id=thread_id, stage="intake")
    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    comms.audit_log(session, candidate.id, "application_submitted", "candidate", "")

    try:
        workflow.start_workflow(candidate.id, job_id, cv_text, thread_id)
    except Exception as e:
        comms.audit_log(session, candidate.id, "workflow_error", "system", str(e))

    return RedirectResponse(url=f"/candidate/{candidate.id}", status_code=303)


# ── Human action (approve/reject) ────────────────────────────────
@app.post("/action/{candidate_id}")
def human_action(
    candidate_id: int,
    decision: str = Form(...),
    comment: str = Form(""),
    interrupt_id: str = Form(""),
    session: Session = Depends(get_session),
):
    candidate = session.get(Candidate, candidate_id)
    if not candidate or not candidate.thread_id:
        return RedirectResponse(url="/", status_code=303)

    try:
        # resolve node name from current interrupt list
        node_name = "action"
        if interrupt_id:
            ws = workflow.get_workflow_state(candidate.thread_id)
            if ws:
                for intr in ws.get("interrupts", []):
                    if intr.get("id") == interrupt_id:
                        node_name = intr.get("node", "action")
                        break

        candidate_label = candidate.name or f"candidate #{candidate_id}"

        if interrupt_id:
            resume_map = {interrupt_id: {"decision": decision, "comment": comment}}
            workflow.resume_workflow(
                candidate.thread_id, decision, comment,
                resume_map=resume_map,
                node_name=node_name,
                candidate_name=candidate_label,
            )
        else:
            workflow.resume_workflow(
                candidate.thread_id, decision, comment,
                node_name=node_name,
                candidate_name=candidate_label,
            )
    except Exception as e:
        comms.audit_log(session, candidate.id, "workflow_resume_error", "system", str(e))

    return RedirectResponse(url=f"/candidate/{candidate_id}", status_code=303)


# ── Inbox ─────────────────────────────────────────────────────────
@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, session: Session = Depends(get_session)):
    role = request.cookies.get("role", "recruiter")
    messages = list(session.exec(select(Message).where(Message.to_role == role).order_by(Message.id.desc())))
    return _render("inbox.html", request, session, messages=messages)


# ── Logs ──────────────────────────────────────────────────────────
@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request, session: Session = Depends(get_session)):
    logs_dir = Path(__file__).parent.parent / "logs"
    all_files = []
    for subdir in ["emails", "slack"]:
        d = logs_dir / subdir
        if d.exists():
            for f in d.iterdir():
                if f.suffix == ".md":
                    all_files.append((f.name, subdir, f))
    log_files = [
        {"name": f"{subdir}/{f.name}", "content": f.read_text()}
        for _, subdir, f in sorted(all_files, key=lambda x: x[0], reverse=True)
    ]

    audit_file = logs_dir / "audit.jsonl"
    audit_lines = []
    if audit_file.exists():
        text = audit_file.read_text().strip()
        if text:
            audit_lines = list(reversed(text.split("\n")))

    return _render("logs.html", request, session, log_files=log_files, audit_lines=audit_lines)


# ── Process Widget (HTMX partial) ────────────────────────────────
@app.get("/widget", response_class=HTMLResponse)
def process_widget(request: Request, session: Session = Depends(get_session)):
    focus_id = request.cookies.get("focus_candidate_id", "")
    candidates = list(session.exec(select(Candidate).where(Candidate.status == "active")))

    stage_counts = {s: 0 for s in STAGE_ORDER}
    for c in session.exec(select(Candidate)):
        stage_counts[c.stage] = stage_counts.get(c.stage, 0) + 1

    focus_candidate = None
    focus_state = None
    if focus_id:
        focus_candidate = session.get(Candidate, int(focus_id))
        if focus_candidate and focus_candidate.thread_id:
            focus_state = workflow.get_workflow_state(focus_candidate.thread_id)

    return templates.TemplateResponse(
        request=request,
        name="_process_widget.html",
        context={
            "request": request,
            "focus_candidate": focus_candidate,
            "focus_state": focus_state,
            "stage_counts": stage_counts,
            "stage_order": STAGE_ORDER,
            "active_candidates": candidates,
        },
    )


@app.post("/set-focus")
def set_focus(candidate_id: str = Form("")):
    resp = RedirectResponse(url="/", status_code=303)
    if candidate_id:
        resp.set_cookie("focus_candidate_id", candidate_id)
    else:
        resp.delete_cookie("focus_candidate_id")
    return resp
