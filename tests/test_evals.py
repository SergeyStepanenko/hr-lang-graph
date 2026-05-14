"""
LLM Evals — real API calls, run with: pytest -m eval

Two layers:
  1. Heuristic evals  — deterministic assertions on LLM output properties
  2. LLM-as-judge     — a second LLM call grades the output quality
"""

import os

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src import llm
from src.schemas import CVScore

pytestmark = pytest.mark.eval

STRONG_CV = """
Alice Johnson
Email: alice.johnson@example.com | Phone: +1-555-0101 | LinkedIn: linkedin.com/in/alicejohnson

Senior ML Engineer, 5 years experience.
- Built LLM-powered customer support agent (GPT-4, LangGraph) at TechCorp
- Designed RAG pipeline over 10M documents
- Led team of 3 engineers
MS Computer Science, Stanford 2019. Skills: Python, LangGraph, LangChain, OpenAI API, PyTorch.
""".strip()

WEAK_CV = """
Bob Smith
Email: bob.smith@email.org

Junior developer, 1 year Python experience.
Built React frontends and some Python scripts. No ML or AI experience.
BS Information Technology, State University 2023.
Skills: JavaScript, React, Python (basic), SQL.
""".strip()

JOB_TITLE = "AI Engineer"
JOB_REQUIREMENTS = (
    "- 3+ years Python experience\n"
    "- Experience with LLMs (OpenAI, Anthropic)\n"
    "- LangChain/LangGraph experience\n"
    "- Strong problem-solving skills"
)


@pytest.fixture(scope="module")
def judge():
    """Cheap LLM judge for output quality evaluation."""
    return ChatOpenAI(
        model="gpt-4o-mini",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )


def llm_judge(judge, question: str, context: str) -> bool:
    """Ask the judge a yes/no question about the output. Returns True if yes."""
    response = judge.invoke([
        SystemMessage(content="You are a strict evaluator. Answer only YES or NO."),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
    ])
    return response.content.strip().upper().startswith("YES")


# ── Parse CV Contact ──────────────────────────────────────────────────────────

class TestParseCvContactEval:
    def test_extracts_correct_email(self):
        result = llm.parse_cv_contact(STRONG_CV)
        assert result.email == "alice.johnson@example.com"

    def test_extracts_name(self):
        result = llm.parse_cv_contact(STRONG_CV)
        assert result.name and len(result.name) > 2
        assert "alice" in result.name.lower() or "johnson" in result.name.lower()

    def test_no_email_returns_none(self):
        cv = "Carol Martinez\nTelegram: @carol_m\n\nML researcher, no email listed."
        result = llm.parse_cv_contact(cv)
        assert result.email is None

    def test_extracts_linkedin(self):
        result = llm.parse_cv_contact(STRONG_CV)
        assert result.linkedin and "linkedin" in result.linkedin.lower()


# ── Score CV ──────────────────────────────────────────────────────────────────

class TestScoreCvEval:
    def test_strong_candidate_scores_high(self):
        score = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert score.score >= 70, f"Strong CV scored too low: {score.score}/100"

    def test_weak_candidate_scores_low(self):
        score = llm.score_cv(WEAK_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert score.score <= 50, f"Weak CV scored too high: {score.score}/100"

    def test_strong_scores_higher_than_weak(self):
        strong = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        weak = llm.score_cv(WEAK_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert strong.score > weak.score, (
            f"Strong ({strong.score}) should beat weak ({weak.score})"
        )

    def test_returns_non_empty_reasoning(self):
        score = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert len(score.reasoning.split()) >= 10

    def test_strong_candidate_has_strengths(self):
        score = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert len(score.strengths) >= 1

    def test_weak_candidate_has_red_flags(self):
        score = llm.score_cv(WEAK_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert len(score.red_flags) >= 1

    def test_score_within_bounds(self):
        score = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        assert 0 <= score.score <= 100

    def test_reasoning_relevant_to_job(self, judge):
        score = llm.score_cv(STRONG_CV, JOB_TITLE, JOB_REQUIREMENTS)
        relevant = llm_judge(
            judge,
            "Does this reasoning mention relevant AI/ML skills or experience?",
            score.reasoning,
        )
        assert relevant, f"Reasoning not relevant to job: {score.reasoning}"


# ── Gen Summary ───────────────────────────────────────────────────────────────

class TestGenSummaryEval:
    def test_returns_non_empty_string(self):
        score = CVScore(score=85, reasoning="Strong ML background", red_flags=[], strengths=["Python", "LLMs"])
        result = llm.gen_summary(STRONG_CV, score)
        assert isinstance(result, str) and len(result) > 30

    def test_reasonable_length(self):
        score = CVScore(score=85, reasoning="Strong", red_flags=[], strengths=["Python"])
        result = llm.gen_summary(STRONG_CV, score)
        words = len(result.split())
        assert 15 <= words <= 250, f"Summary length unexpected: {words} words"

    def test_summary_is_recruiter_friendly(self, judge):
        score = CVScore(score=85, reasoning="Strong ML background", red_flags=[], strengths=["Python", "LLMs"])
        result = llm.gen_summary(STRONG_CV, score)
        useful = llm_judge(
            judge,
            "Is this a useful, professional candidate summary that a recruiter would find helpful?",
            result,
        )
        assert useful, f"Summary not recruiter-friendly: {result}"


# ── Gen Offer ─────────────────────────────────────────────────────────────────

class TestGenOfferEval:
    def test_mentions_candidate_name(self):
        result = llm.gen_offer("Alice Johnson", "AI Engineer")
        assert "alice" in result.lower()

    def test_mentions_position(self):
        result = llm.gen_offer("Alice Johnson", "AI Engineer")
        assert "engineer" in result.lower()

    def test_professional_tone(self, judge):
        result = llm.gen_offer("Alice Johnson", "AI Engineer")
        professional = llm_judge(
            judge,
            "Is this a professional job offer letter suitable to send to a candidate?",
            result,
        )
        assert professional, f"Offer not professional: {result}"


# ── Gen Rejection ─────────────────────────────────────────────────────────────

class TestGenRejectionEval:
    def test_mentions_candidate_name(self):
        result = llm.gen_rejection("Bob Smith", "Did not meet requirements")
        assert "bob" in result.lower()

    def test_reasonable_length(self):
        result = llm.gen_rejection("Bob Smith", "Did not meet requirements")
        words = len(result.split())
        assert 10 <= words <= 150, f"Rejection length unexpected: {words} words"

    def test_empathetic_tone(self, judge):
        result = llm.gen_rejection("Bob Smith", "Insufficient Python experience")
        empathetic = llm_judge(
            judge,
            "Is this rejection email professional and empathetic, not rude or cold?",
            result,
        )
        assert empathetic, f"Rejection not empathetic: {result}"

    def test_does_not_reveal_internal_reason_verbatim(self, judge):
        result = llm.gen_rejection("Bob Smith", "Candidate is too junior and lacks focus")
        tactful = llm_judge(
            judge,
            'Does this email avoid repeating harsh internal notes like "too junior" verbatim, keeping the message professional?',
            result,
        )
        assert tactful, f"Rejection reveals internal reasoning: {result}"
