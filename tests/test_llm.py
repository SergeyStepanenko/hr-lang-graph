"""Unit tests for src/llm.py — mock the ChatOpenAI client."""

from unittest.mock import MagicMock, patch

import pytest

import src.llm as llm_module
from src.schemas import CandidateContact, CVScore


@pytest.fixture(autouse=True)
def reset_llm_singleton():
    """Ensure the LLM singleton doesn't leak between tests."""
    llm_module._llm = None
    yield
    llm_module._llm = None


def _mock_llm_structured(return_value):
    """Mock _get_llm() for structured output calls."""
    mock_llm = MagicMock()
    mock_chain = MagicMock()
    mock_llm.with_structured_output.return_value = mock_chain
    mock_chain.with_config.return_value = mock_chain
    mock_chain.invoke.return_value = return_value
    return mock_llm, mock_chain


def _mock_llm_plain(text: str):
    """Mock _get_llm() for plain text calls."""
    mock_llm = MagicMock()
    mock_llm.with_config.return_value = mock_llm
    response = MagicMock()
    response.content = text
    mock_llm.invoke.return_value = response
    return mock_llm


class TestParseCvContact:
    def test_returns_structured_output(self):
        expected = CandidateContact(name="Alice", email="alice@example.com", phone="+1-555-0101")
        mock_llm, _ = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.parse_cv_contact("Alice Johnson\nEmail: alice@example.com")
        assert result.name == "Alice"
        assert result.email == "alice@example.com"
        assert result.phone == "+1-555-0101"

    def test_no_email_returns_none(self):
        expected = CandidateContact(name="Carol", email=None, telegram="@carol")
        mock_llm, _ = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.parse_cv_contact("Carol Martinez\nTelegram: @carol")
        assert result.email is None
        assert result.telegram == "@carol"

    def test_uses_structured_output_with_correct_schema(self):
        expected = CandidateContact(name="Bob", email=None)
        mock_llm, mock_chain = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.parse_cv_contact("Bob Smith")
        mock_llm.with_structured_output.assert_called_once_with(CandidateContact)

    def test_system_message_mentions_contact_fields(self):
        expected = CandidateContact(name="Bob", email=None)
        mock_llm, mock_chain = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.parse_cv_contact("Bob Smith")
        messages = mock_chain.invoke.call_args[0][0]
        system_content = messages[0].content
        assert "email" in system_content.lower()
        assert "linkedin" in system_content.lower()


class TestScoreCv:
    def test_returns_score_object(self):
        expected = CVScore(score=85, reasoning="Strong candidate", red_flags=[], strengths=["Python", "LLMs"])
        mock_llm, _ = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.score_cv("cv text", "AI Engineer", "Python, LLMs")
        assert result.score == 85
        assert result.reasoning == "Strong candidate"
        assert "Python" in result.strengths

    def test_low_score_candidate(self):
        expected = CVScore(score=20, reasoning="No relevant experience", red_flags=["No ML experience"], strengths=[])
        mock_llm, _ = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.score_cv("cv text", "AI Engineer", "Python, LLMs")
        assert result.score == 20
        assert "No ML experience" in result.red_flags

    def test_injects_job_context_in_system_message(self):
        expected = CVScore(score=50, reasoning="ok", red_flags=[], strengths=[])
        mock_llm, mock_chain = _mock_llm_structured(expected)
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.score_cv("cv text", "Senior AI Engineer", "Python 5+ years")
        messages = mock_chain.invoke.call_args[0][0]
        system_content = messages[0].content
        assert "Senior AI Engineer" in system_content
        assert "Python 5+ years" in system_content


class TestGenSummary:
    def test_returns_string(self):
        mock_llm = _mock_llm_plain("Great candidate with 5 years of experience.")
        score = CVScore(score=85, reasoning="Good", red_flags=[], strengths=["Python"])
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.gen_summary("cv text", score)
        assert result == "Great candidate with 5 years of experience."

    def test_includes_score_in_user_message(self):
        mock_llm = _mock_llm_plain("Summary here.")
        score = CVScore(score=72, reasoning="Solid", red_flags=["gap"], strengths=["ML"])
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.gen_summary("cv text", score)
        messages = mock_llm.invoke.call_args[0][0]
        user_content = messages[1].content
        assert "72/100" in user_content
        assert "gap" in user_content
        assert "ML" in user_content


class TestGenOffer:
    def test_returns_string(self):
        mock_llm = _mock_llm_plain("We are pleased to offer you the position.")
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.gen_offer("Alice Johnson", "AI Engineer")
        assert result == "We are pleased to offer you the position."

    def test_includes_candidate_and_job_in_user_message(self):
        mock_llm = _mock_llm_plain("Offer text.")
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.gen_offer("Alice Johnson", "Senior AI Engineer")
        messages = mock_llm.invoke.call_args[0][0]
        user_content = messages[1].content
        assert "Alice Johnson" in user_content
        assert "Senior AI Engineer" in user_content


class TestGenRejection:
    def test_returns_string(self):
        mock_llm = _mock_llm_plain("We regret to inform you...")
        with patch("src.llm._get_llm", return_value=mock_llm):
            result = llm_module.gen_rejection("Bob Smith", "Did not meet requirements")
        assert result == "We regret to inform you..."

    def test_includes_candidate_and_reason_in_user_message(self):
        mock_llm = _mock_llm_plain("Rejection text.")
        with patch("src.llm._get_llm", return_value=mock_llm):
            llm_module.gen_rejection("Bob Smith", "Insufficient Python experience")
        messages = mock_llm.invoke.call_args[0][0]
        user_content = messages[1].content
        assert "Bob Smith" in user_content
        assert "Insufficient Python experience" in user_content
