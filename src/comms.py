import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from src.models import AuditEvent, Message
from src import clock as vclock

LOGS_DIR = Path(__file__).parent.parent / "logs"


def send_email(
    session: Session,
    candidate_id: int,
    to_role: str,
    subject: str,
    body: str,
    to_email: str | None = None,
):
    day = vclock.now(session)

    msg = Message(
        candidate_id=candidate_id,
        to_role=to_role,
        to_email=to_email,
        channel="email",
        subject=subject,
        body=body,
        created_at_virtual=day,
    )
    session.add(msg)
    session.commit()

    email_dir = LOGS_DIR / "emails"
    email_dir.mkdir(parents=True, exist_ok=True)
    fname = email_dir / f"{day:04d}_{candidate_id}_{to_role}_{msg.id}.md"
    fname.write_text(
        f"# Email\n\n"
        f"**To:** {to_role}" + (f" ({to_email})" if to_email else "") + "\n"
        f"**Subject:** {subject}\n"
        f"**Day:** {day}\n\n"
        f"{body}\n"
    )


def send_slack(
    session: Session,
    candidate_id: int,
    channel: str,
    to_role: str,
    message: str,
):
    day = vclock.now(session)

    msg = Message(
        candidate_id=candidate_id,
        to_role=to_role,
        channel="slack",
        subject=f"#{channel}",
        body=message,
        created_at_virtual=day,
    )
    session.add(msg)
    session.commit()

    slack_dir = LOGS_DIR / "slack"
    slack_dir.mkdir(parents=True, exist_ok=True)
    fname = slack_dir / f"{day:04d}_{candidate_id}_{channel}_{msg.id}.md"
    fname.write_text(
        f"# Slack — #{channel}\n\n"
        f"**To:** {to_role}\n"
        f"**Day:** {day}\n\n"
        f"{message}\n"
    )


def audit_log(
    session: Session,
    candidate_id: int,
    event: str,
    actor: str,
    reasoning: str = "",
):
    day = vclock.now(session)

    ae = AuditEvent(
        candidate_id=candidate_id,
        event=event,
        actor=actor,
        reasoning=reasoning,
        clock_day=day,
    )
    session.add(ae)
    session.commit()

    audit_file = LOGS_DIR / "audit.jsonl"
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_file, "a") as f:
        f.write(
            json.dumps(
                {
                    "id": ae.id,
                    "candidate_id": candidate_id,
                    "event": event,
                    "actor": actor,
                    "reasoning": reasoning,
                    "clock_day": day,
                    "ts": datetime.utcnow().isoformat(),
                }
            )
            + "\n"
        )
