from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

STAGES = ("intake", "screening", "approvals", "interview", "offer", "hired", "rejected")
STATUSES = ("active", "rejected", "hired")
ROLES = ("candidate", "recruiter", "hm", "cfo", "legal", "interviewer")


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    description: str
    requirements: str


class Candidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    linkedin: Optional[str] = None
    cv_text: str = ""
    job_id: int = Field(foreign_key="job.id")
    stage: str = "intake"
    status: str = "active"
    thread_id: Optional[str] = None
    no_contact: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id")
    to_role: str
    to_email: Optional[str] = None
    channel: str = "email"
    subject: str = ""
    body: str = ""
    created_at_virtual: int = 0


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id")
    event: str
    actor: str
    reasoning: str = ""
    clock_day: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Clock(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    current_day: int = 0
