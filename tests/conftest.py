import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.models import Candidate, Clock, Job


@pytest.fixture
def test_engine():
    # StaticPool shares one connection so in-memory data is visible across sessions
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_job(test_engine):
    with Session(test_engine) as session:
        job = Job(
            title="AI Engineer",
            description="Build AI systems",
            requirements="Python, LLMs, LangGraph",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


@pytest.fixture
def test_candidate(test_engine, test_job):
    with Session(test_engine) as session:
        candidate = Candidate(
            name="",
            cv_text="Alice Johnson\nEmail: alice@example.com\nPhone: +1-555-0101",
            job_id=test_job.id,
            stage="intake",
            status="active",
        )
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
        return candidate


@pytest.fixture
def test_clock(test_engine):
    with Session(test_engine) as session:
        clock = Clock(current_day=0)
        session.add(clock)
        session.commit()
        return clock
