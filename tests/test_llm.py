"""Unit tests for src/llm.py — mock the instructor/OpenAI client."""

from unittest.mock import MagicMock, patch

import pytest

import src.llm as llm_module
from src.schemas import CandidateContact, CVScore


@pytest.fixture(autouse=True)
def reset_llm_client():
    """Ensure the LLM singleton doesn't leak between tests."""
    original = llm_module._client
    llm_module._client = None
    yield
    llm_module._client = None


def _mock_client(return_value):
    mock = MagicMock()
    mock.chat.completions.create.return_value = return_value
    return mock


def _text_response(text: str):
    resp = MagicMock()
    resp.choices[0].message.content = text
    return resp


class TestParseCvContact:
    def test_returns_structured_output(self):
        expected = CandidateContact(name="Alice", email="alice@example.com", phone="+1-555-0101")
        with patch("src.llm._get_client", return_value=_mock_client(expected)):
            result = llm_module.parse_cv_contact("Alice Johnson\nEmail: alice@example.com")
        assert result.name == "Alice"
        assert result.email == "alice@example.com"
        assert result.phone == "+1-555-0101"

    def test_no_email_returns_none(self):
        expected = CandidateContact(name="Carol", email=None, telegram="@carol")
        with patch("src.llm._get_client", return_value=_mock_client(expected)):
            result = llm_module.parse_cv_contact("Carol Martinez\nTelegram: @carol")
        assert result.email is None
        assert result.telegram == "@carol"

    def test_calls_correct_model(self):
        expected = CandidateContact(name="Bob", email=None)
        mock_client = _mock_client(expected)
        with patch("src.llm._get_client", return_value=mock_client):
            llm_module.parse_cv_contact("Bob Smith")
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == llm_module.MODEL
        assert call_kwargs.kwargs["response_model"] == CandidateContact


class TestScoreCv:
    def test_returns_score_object(self):
        expected = CVScore(score=85, reasoning="Strong candidate", red_flags=[], strengths=["Python", "LLMs"])
        with patch("src.llm._get_client", return_value=_mock_client(expected)):
            result = llm_module.score_cv("cv text", "AI Engineer", "Python, LLMs")
        assert result.score == 85
        assert result.reasoning == "Strong candidate"
        assert "Python" in result.strengths

    def test_low_score_candidate(self):
        expected = CVScore(score=20, reasoning="No relevant experience", red_flags=["No ML experience"], strengths=[])
        with patch("src.llm._get_client", return_value=_mock_client(expected)):
            result = llm_module.score_cv("cv text", "AI Engineer", "Python, LLMs")
        assert result.score == 20
        assert "No ML experience" in result.red_flags

    def test_injects_job_context_in_system_message(self):
        expected = CVScore(score=50, reasoning="ok", red_flags=[], strengths=[])
        mock_client = _mock_client(expected)
        with patch("src.llm._get_client", return_value=mock_client):
            llm_module.score_cv("cv text", "Senior AI Engineer", "Python 5+ years")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "Senior AI Engineer" in system_msg
        assert "Python 5+ years" in system_msg


class TestGenSummary:
    def test_returns_string(self):
        mock_client = _mock_client(_text_response("Great candidate with 5 years of experience."))
        score = CVScore(score=85, reasoning="Good", red_flags=[], strengths=["Python"])
        with patch("src.llm._get_client", return_value=mock_client):
            result = llm_module.gen_summary("cv text", score)
        assert result == "Great candidate with 5 years of experience."

    def test_includes_score_in_user_message(self):
        mock_client = _mock_client(_text_response("Summary here."))
        score = CVScore(score=72, reasoning="Solid", red_flags=["gap"], strengths=["ML"])
        with patch("src.llm._get_client", return_value=mock_client):
            llm_module.gen_summary("cv text", score)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "72/100" in user_msg
        assert "gap" in user_msg
        assert "ML" in user_msg


class TestGenOffer:
    def test_returns_string(self):
        mock_client = _mock_client(_text_response("We are pleased to offer you the position."))
        with patch("src.llm._get_client", return_value=mock_client):
            result = llm_module.gen_offer("Alice Johnson", "AI Engineer")
        assert result == "We are pleased to offer you the position."

    def test_includes_candidate_and_job_in_user_message(self):
        mock_client = _mock_client(_text_response("Offer text."))
        with patch("src.llm._get_client", return_value=mock_client):
            llm_module.gen_offer("Alice Johnson", "Senior AI Engineer")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "Alice Johnson" in user_msg
        assert "Senior AI Engineer" in user_msg


class TestGenRejection:
    def test_returns_string(self):
        mock_client = _mock_client(_text_response("We regret to inform you..."))
        with patch("src.llm._get_client", return_value=mock_client):
            result = llm_module.gen_rejection("Bob Smith", "Did not meet requirements")
        assert result == "We regret to inform you..."

    def test_includes_candidate_and_reason_in_user_message(self):
        mock_client = _mock_client(_text_response("Rejection text."))
        with patch("src.llm._get_client", return_value=mock_client):
            llm_module.gen_rejection("Bob Smith", "Insufficient Python experience")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_msg = messages[1]["content"]
        assert "Bob Smith" in user_msg
        assert "Insufficient Python experience" in user_msg
