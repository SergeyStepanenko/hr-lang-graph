"""Integration tests for src/nodes.py.

LLM calls are mocked; DB uses in-memory SQLite (StaticPool).
comms file I/O is mocked to avoid filesystem side effects.
LangGraph interrupt() is mocked to return controlled human decisions.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from src.models import Candidate
from src.schemas import CandidateContact, CVScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_candidate(engine, candidate_id: int) -> Candidate:
    with Session(engine) as session:
        return session.get(Candidate, candidate_id)


def _comms_patches():
    """Context manager stack that suppresses all comms file/DB side effects."""
    return [
        patch("src.comms.audit_log"),
        patch("src.comms.send_email"),
        patch("src.comms.send_slack"),
    ]


# ---------------------------------------------------------------------------
# intake node
# ---------------------------------------------------------------------------

class TestIntakeNode:
    def test_with_email_updates_candidate_and_returns_state(
        self, test_engine, test_candidate, test_clock
    ):
        contact = CandidateContact(
            name="Alice Johnson",
            email="alice@example.com",
            phone="+1-555-0101",
            telegram="@alice",
            linkedin=None,
        )
        state = {"cv_text": test_candidate.cv_text, "candidate_id": test_candidate.id}

        with patch("src.llm.parse_cv_contact", return_value=contact), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.intake(state)

        assert result["stage"] == "screening"
        assert result["candidate_name"] == "Alice Johnson"
        assert result["candidate_email"] == "alice@example.com"
        assert result["no_contact"] is False

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.name == "Alice Johnson"
        assert updated.email == "alice@example.com"
        assert updated.stage == "screening"
        assert updated.no_contact is False

    def test_without_email_sets_no_contact(self, test_engine, test_candidate, test_clock):
        contact = CandidateContact(
            name="Carol Martinez",
            email=None,
            telegram="@carol",
            phone=None,
            linkedin=None,
        )
        state = {"cv_text": test_candidate.cv_text, "candidate_id": test_candidate.id}

        with patch("src.llm.parse_cv_contact", return_value=contact), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email") as mock_email, \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.intake(state)

        assert result["no_contact"] is True
        assert result["candidate_email"] is None
        mock_email.assert_not_called()

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.no_contact is True
        assert updated.email is None

    def test_sends_welcome_email_when_email_present(self, test_engine, test_candidate, test_clock):
        contact = CandidateContact(name="Alice", email="alice@example.com")
        state = {"cv_text": test_candidate.cv_text, "candidate_id": test_candidate.id}

        with patch("src.llm.parse_cv_contact", return_value=contact), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email") as mock_email, \
             patch("src.comms.send_slack"):
            from src import nodes
            nodes.intake(state)

        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args
        assert call_kwargs.args[3] == "Application Received"  # subject


# ---------------------------------------------------------------------------
# score_cv node
# ---------------------------------------------------------------------------

class TestScoreCvNode:
    def test_returns_score_and_summary(self, test_engine, test_candidate, test_job, test_clock):
        # candidate must have a job_id set; test_candidate already has test_job.id
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice Johnson"
            candidate.job_id = test_job.id
            session.add(candidate)
            session.commit()

        score = CVScore(score=85, reasoning="Strong", red_flags=[], strengths=["Python"])
        state = {
            "cv_text": test_candidate.cv_text,
            "candidate_id": test_candidate.id,
            "clock_day": 0,
        }

        with patch("src.llm.score_cv", return_value=score), \
             patch("src.llm.gen_summary", return_value="Great AI engineer with 5 years experience."), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.score_cv(state)

        assert result["score"]["score"] == 85
        assert result["score"]["reasoning"] == "Strong"
        assert result["summary"] == "Great AI engineer with 5 years experience."

    def test_score_sent_to_slack(self, test_engine, test_candidate, test_job, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice Johnson"
            session.add(candidate)
            session.commit()

        score = CVScore(score=72, reasoning="Decent", red_flags=["gap"], strengths=["ML"])
        state = {"cv_text": "cv", "candidate_id": test_candidate.id, "clock_day": 0}

        with patch("src.llm.score_cv", return_value=score), \
             patch("src.llm.gen_summary", return_value="Summary."), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack") as mock_slack:
            from src import nodes
            nodes.score_cv(state)

        mock_slack.assert_called_once()
        slack_msg = mock_slack.call_args.args[4]
        assert "72/100" in slack_msg


# ---------------------------------------------------------------------------
# recruiter_review node
# ---------------------------------------------------------------------------

class TestRecruiterReviewNode:
    def test_approve_advances_to_approvals(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice Johnson"
            candidate.email = "alice@example.com"
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "candidate_name": "Alice Johnson",
            "score": {"score": 85},
            "summary": "Good candidate.",
            "clock_day": 0,
        }

        with patch("src.nodes.interrupt", return_value={"decision": "approve", "comment": "Looks good"}), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.recruiter_review(state)

        assert result["stage"] == "approvals"
        assert result["approvals"] == {"hm": "pending", "cfo": "pending", "legal": "pending"}

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "approvals"

    def test_reject_sets_rejected_stage_and_sends_rejection_email(
        self, test_engine, test_candidate, test_clock
    ):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Bob Smith"
            candidate.email = "bob@example.com"
            candidate.no_contact = False
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "candidate_name": "Bob Smith",
            "score": {"score": 20},
            "summary": "Weak candidate.",
            "clock_day": 0,
        }

        with patch("src.nodes.interrupt", return_value={"decision": "reject", "comment": "Too junior"}), \
             patch("src.nodes.engine", test_engine), \
             patch("src.llm.gen_rejection", return_value="Sorry, not a fit."), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email") as mock_email, \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.recruiter_review(state)

        assert result["stage"] == "rejected"

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "rejected"
        assert updated.status == "rejected"

        mock_email.assert_called_once()
        assert mock_email.call_args.args[3] == "Application Update"

    def test_reject_no_contact_skips_email(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Carol"
            candidate.email = None
            candidate.no_contact = True
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "candidate_name": "Carol",
            "score": {"score": 30},
            "summary": "Weak.",
            "clock_day": 0,
        }

        with patch("src.nodes.interrupt", return_value={"decision": "reject", "comment": ""}), \
             patch("src.nodes.engine", test_engine), \
             patch("src.llm.gen_rejection", return_value="Sorry."), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email") as mock_email, \
             patch("src.comms.send_slack"):
            from src import nodes
            nodes.recruiter_review(state)

        mock_email.assert_not_called()


# ---------------------------------------------------------------------------
# aggregate_approvals node
# ---------------------------------------------------------------------------

class TestAggregateApprovalsNode:
    def test_all_approved_advances_to_interview(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice"
            candidate.email = "alice@example.com"
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "approvals": {"hm": "pending", "cfo": "pending", "legal": "pending"},
            "approval_results": [
                {"approver": "hm", "approval_decision": "approved", "approval_comment": ""},
                {"approver": "cfo", "approval_decision": "approved", "approval_comment": ""},
                {"approver": "legal", "approval_decision": "approved", "approval_comment": ""},
            ],
            "clock_day": 0,
        }

        with patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.aggregate_approvals(state)

        assert result["stage"] == "interview"
        assert result["approvals"] == {"hm": "approved", "cfo": "approved", "legal": "approved"}

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "interview"

    def test_any_rejected_sets_rejected(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Bob"
            candidate.email = "bob@example.com"
            candidate.no_contact = False
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "approvals": {},
            "approval_results": [
                {"approver": "hm", "approval_decision": "approved", "approval_comment": ""},
                {"approver": "cfo", "approval_decision": "rejected", "approval_comment": "Budget"},
                {"approver": "legal", "approval_decision": "approved", "approval_comment": ""},
            ],
            "clock_day": 0,
        }

        with patch("src.nodes.engine", test_engine), \
             patch("src.llm.gen_rejection", return_value="Rejected."), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.aggregate_approvals(state)

        assert result["stage"] == "rejected"

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "rejected"
        assert updated.status == "rejected"

    def test_partial_approvals_stays_pending(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice"
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "approvals": {"hm": "pending", "cfo": "pending", "legal": "pending"},
            "approval_results": [
                {"approver": "hm", "approval_decision": "approved", "approval_comment": ""},
            ],
            "clock_day": 0,
        }

        with patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.aggregate_approvals(state)

        # not all approved, not any rejected → stays in approvals
        assert result["stage"] == "approvals"


# ---------------------------------------------------------------------------
# offer_generate node
# ---------------------------------------------------------------------------

class TestOfferGenerateNode:
    def test_generates_offer_text(self, test_engine, test_candidate, test_job, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice Johnson"
            candidate.job_id = test_job.id
            session.add(candidate)
            session.commit()

        state = {"candidate_id": test_candidate.id, "clock_day": 0}

        with patch("src.llm.gen_offer", return_value="We offer you the AI Engineer role."), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.offer_generate(state)

        assert result["offer_text"] == "We offer you the AI Engineer role."


# ---------------------------------------------------------------------------
# offer_candidate_decision node
# ---------------------------------------------------------------------------

class TestOfferCandidateDecisionNode:
    def test_accept_sets_hired(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice"
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "candidate_name": "Alice",
            "offer_text": "We offer you the position.",
            "clock_day": 0,
        }

        with patch("src.nodes.interrupt", return_value={"decision": "approve"}), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.offer_candidate_decision(state)

        assert result["stage"] == "hired"

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "hired"
        assert updated.status == "hired"

    def test_reject_offer_sets_rejected(self, test_engine, test_candidate, test_clock):
        with Session(test_engine) as session:
            candidate = session.get(Candidate, test_candidate.id)
            candidate.name = "Alice"
            session.add(candidate)
            session.commit()

        state = {
            "candidate_id": test_candidate.id,
            "candidate_name": "Alice",
            "offer_text": "Offer text.",
            "clock_day": 0,
        }

        with patch("src.nodes.interrupt", return_value={"decision": "reject"}), \
             patch("src.nodes.engine", test_engine), \
             patch("src.comms.audit_log"), \
             patch("src.comms.send_email"), \
             patch("src.comms.send_slack"):
            from src import nodes
            result = nodes.offer_candidate_decision(state)

        assert result["stage"] == "rejected"

        updated = _get_candidate(test_engine, test_candidate.id)
        assert updated.stage == "rejected"
        assert updated.status == "rejected"
