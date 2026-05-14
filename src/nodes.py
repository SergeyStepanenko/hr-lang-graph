"""LangGraph node functions for the recruiting pipeline."""

from langgraph.types import Command, interrupt
from sqlmodel import Session

from src import clock as vclock
from src import comms, llm
from src.db import engine
from src.models import Candidate, Job


def intake(state: dict) -> dict:
    """Parse CV, extract contacts, create/update candidate."""
    cv_text = state["cv_text"]
    candidate_id = state["candidate_id"]

    contact = llm.parse_cv_contact(cv_text)

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)
        if candidate is None:
            candidate = Candidate(
                id=candidate_id,
                cv_text=cv_text,
                job_id=state.get("job_id", 1),
                thread_id=state.get("thread_id", ""),
                stage="intake",
            )
            session.add(candidate)
            session.flush()
        candidate.name = contact.name
        candidate.email = contact.email
        candidate.phone = contact.phone
        candidate.telegram = contact.telegram
        candidate.linkedin = contact.linkedin
        candidate.stage = "screening"

        no_contact = contact.email is None
        candidate.no_contact = no_contact

        session.add(candidate)
        session.commit()

        comms.audit_log(session, candidate_id, "intake_complete", "system",
                        f"Parsed: {contact.name}, email={contact.email}")

        if no_contact:
            comms.audit_log(session, candidate_id, "no_contact_warning", "system",
                            "No email found — communications disabled")
        else:
            comms.send_email(
                session, candidate_id, "candidate", "Application Received",
                f"Dear {contact.name},\n\nThank you for applying! We will review your CV shortly.\n\nBest regards,\nHR Team",
                to_email=contact.email,
            )

    return {
        "stage": "screening",
        "candidate_name": contact.name,
        "candidate_email": contact.email,
        "no_contact": no_contact,
    }


def score_cv(state: dict) -> dict:
    """AI scores the CV."""
    cv_text = state["cv_text"]
    candidate_id = state["candidate_id"]

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)
        job = session.get(Job, candidate.job_id)
        score = llm.score_cv(cv_text, job.title, job.requirements)
        summary = llm.gen_summary(cv_text, score)

        comms.audit_log(session, candidate_id, "cv_scored", "ai",
                        f"Score: {score.score}/100. {score.reasoning}")
        comms.send_slack(
            session, candidate_id, "recruiting", "recruiter",
            f"📋 New CV scored: {candidate.name} — {score.score}/100\n\n{summary}",
        )

    return {
        "score": score.model_dump(),
        "summary": summary,
        "last_action_day": state.get("clock_day", 0),
    }


def recruiter_review(state: dict) -> dict:
    """Recruiter approves/rejects after seeing score."""
    candidate_id = state["candidate_id"]

    decision = interrupt({
        "type": "recruiter_review",
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "score": state.get("score", {}),
        "summary": state.get("summary", ""),
        "message": "Review CV score and approve or reject this candidate.",
    })

    human_decision = decision.get("decision", "approve")
    reason = decision.get("comment", "")

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if human_decision == "reject":
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()

            comms.audit_log(session, candidate_id, "recruiter_rejected", "recruiter", reason)

            if not candidate.no_contact and candidate.email:
                rejection_text = llm.gen_rejection(candidate.name, reason or "Did not meet requirements")
                comms.send_email(session, candidate_id, "candidate", "Application Update",
                                 rejection_text, to_email=candidate.email)

            return {"stage": "rejected", "last_action_day": vclock.now(session)}

        candidate.stage = "approvals"
        session.add(candidate)
        session.commit()
        comms.audit_log(session, candidate_id, "recruiter_approved", "recruiter", reason)

    return {
        "stage": "approvals",
        "approvals": {"hm": "pending", "cfo": "pending", "legal": "pending"},
        "last_action_day": state.get("clock_day", 0),
    }


def approval_hm(state: dict) -> dict:
    return _do_approval(state, "hm")


def approval_cfo(state: dict) -> dict:
    return _do_approval(state, "cfo")


def approval_legal(state: dict) -> dict:
    return _do_approval(state, "legal")


def _do_approval(state: dict, role: str) -> dict:
    """Process single approval with interrupt."""
    candidate_id = state["candidate_id"]

    decision = interrupt({
        "type": f"approval_{role}",
        "role": role,
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "message": f"{role.upper()} approval needed for this candidate.",
    })

    human_decision = decision.get("decision", "approved")
    comment = decision.get("comment", "")

    with Session(engine) as session:
        comms.audit_log(session, candidate_id, f"approval_{role}_{human_decision}", role, comment)
        if human_decision in ("approved", "rejected"):
            comms.send_slack(
                session, candidate_id, "recruiting", "recruiter",
                f"{'✅' if human_decision == 'approved' else '❌'} {role.upper()} {human_decision}: {state.get('candidate_name', '')} — {comment}",
            )

    return {"approval_results": [{"approver": role, "approval_decision": human_decision, "approval_comment": comment}]}


def aggregate_approvals(state: dict) -> dict:
    """Fan-in: check all approvals, decide next step."""
    candidate_id = state["candidate_id"]
    approvals = dict(state.get("approvals", {}))

    for r in state.get("approval_results", []):
        approvals[r["approver"]] = r["approval_decision"]

    any_rejected = any(v == "rejected" for v in approvals.values())
    all_approved = all(v == "approved" for v in approvals.values())

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if any_rejected:
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "approvals_vetoed", "system", f"Approvals: {approvals}")
            if not candidate.no_contact and candidate.email:
                rejection_text = llm.gen_rejection(candidate.name, "Internal review did not proceed")
                comms.send_email(session, candidate_id, "candidate", "Application Update",
                                 rejection_text, to_email=candidate.email)
            return {"approvals": approvals, "stage": "rejected"}

        if all_approved:
            candidate.stage = "interview"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "all_approved", "system", f"Approvals: {approvals}")
            return {"approvals": approvals, "stage": "interview", "last_action_day": vclock.now(session)}

    return {"approvals": approvals, "stage": "approvals"}


def interview_schedule(state: dict) -> dict:
    """Candidate accepts/declines interview slot."""
    candidate_id = state["candidate_id"]

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)
        if not candidate.no_contact and candidate.email:
            comms.send_email(session, candidate_id, "candidate", "Interview Invitation",
                             f"Dear {candidate.name},\n\nWe'd like to schedule an interview. Please accept or decline.",
                             to_email=candidate.email)

    decision = interrupt({
        "type": "interview_schedule",
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "message": "Accept or decline the interview invitation.",
    })

    human_decision = decision.get("decision", "approve")

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if human_decision == "decline":
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "interview_declined", "candidate", "")
            return {"stage": "rejected"}

        comms.audit_log(session, candidate_id, "interview_accepted", "candidate", "")
        comms.send_email(session, candidate_id, "interviewer", "Interview Scheduled",
                         f"Interview with {candidate.name} has been confirmed.")

    return {"stage": "interview", "interview": "scheduled", "last_action_day": state.get("clock_day", 0)}


def interview_scorecard(state: dict) -> dict:
    """Interviewer submits scorecard."""
    candidate_id = state["candidate_id"]

    decision = interrupt({
        "type": "interview_scorecard",
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "message": "Submit interview scorecard — approve or reject.",
    })

    human_decision = decision.get("decision", "approve")
    comment = decision.get("comment", "")

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if human_decision == "reject":
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "interview_rejected", "interviewer", comment)
            if not candidate.no_contact and candidate.email:
                rejection_text = llm.gen_rejection(candidate.name, "Interview feedback")
                comms.send_email(session, candidate_id, "candidate", "Application Update",
                                 rejection_text, to_email=candidate.email)
            return {"stage": "rejected"}

        candidate.stage = "offer"
        session.add(candidate)
        session.commit()
        comms.audit_log(session, candidate_id, "interview_passed", "interviewer", comment)

    return {"stage": "offer", "interview_score": comment, "last_action_day": state.get("clock_day", 0)}


def offer_generate(state: dict) -> dict:
    """AI generates offer draft."""
    candidate_id = state["candidate_id"]

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)
        job = session.get(Job, candidate.job_id)
        offer_text = llm.gen_offer(candidate.name, job.title)

        comms.audit_log(session, candidate_id, "offer_drafted", "ai", "")
        comms.send_slack(session, candidate_id, "recruiting", "recruiter",
                         f"📝 Offer draft ready for {candidate.name}")

    return {"offer_text": offer_text, "last_action_day": state.get("clock_day", 0)}


def offer_recruiter_review(state: dict) -> dict:
    """Recruiter approves/edits offer."""
    candidate_id = state["candidate_id"]

    decision = interrupt({
        "type": "offer_recruiter_review",
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "offer_text": state.get("offer_text", ""),
        "message": "Review and approve the offer draft.",
    })

    human_decision = decision.get("decision", "approve")

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if human_decision == "reject":
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "offer_withdrawn", "recruiter", "")
            return {"stage": "rejected"}

        comms.audit_log(session, candidate_id, "offer_approved_by_recruiter", "recruiter", "")

        if not candidate.no_contact and candidate.email:
            comms.send_email(session, candidate_id, "candidate", "Job Offer",
                             state.get("offer_text", "We would like to offer you the position."),
                             to_email=candidate.email)

    return {"stage": "offer", "last_action_day": state.get("clock_day", 0)}


def offer_candidate_decision(state: dict) -> dict:
    """Candidate accepts/rejects offer."""
    candidate_id = state["candidate_id"]

    decision = interrupt({
        "type": "offer_candidate_decision",
        "candidate_id": candidate_id,
        "candidate_name": state.get("candidate_name", ""),
        "offer_text": state.get("offer_text", ""),
        "message": "Accept or reject the job offer.",
    })

    human_decision = decision.get("decision", "approve")

    with Session(engine) as session:
        candidate = session.get(Candidate, candidate_id)

        if human_decision == "reject":
            candidate.stage = "rejected"
            candidate.status = "rejected"
            session.add(candidate)
            session.commit()
            comms.audit_log(session, candidate_id, "offer_rejected", "candidate", "")
            return {"stage": "rejected"}

        candidate.stage = "hired"
        candidate.status = "hired"
        session.add(candidate)
        session.commit()
        comms.audit_log(session, candidate_id, "offer_accepted", "candidate", "")
        comms.send_slack(session, candidate_id, "recruiting", "recruiter",
                         f"🎉 {candidate.name} accepted the offer!")

    return {"stage": "hired"}
