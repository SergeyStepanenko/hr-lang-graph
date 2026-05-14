import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.schemas import CandidateContact, CVScore

MODEL = "gpt-4o-mini"
_llm = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=MODEL, api_key=os.environ.get("OPENAI_API_KEY"))
    return _llm


def parse_cv_contact(cv_text: str) -> CandidateContact:
    chain = _get_llm().with_structured_output(CandidateContact)
    return chain.invoke([
        SystemMessage(content=(
            "Extract contact information from this CV. "
            "Return the candidate's name and any contact details you find. "
            "Fields: name, email, phone, telegram, linkedin. "
            "Set fields to null if not found in the text."
        )),
        HumanMessage(content=cv_text),
    ])


def score_cv(cv_text: str, job_title: str, job_requirements: str) -> CVScore:
    chain = _get_llm().with_structured_output(CVScore)
    return chain.invoke([
        SystemMessage(content=(
            f"You are an HR screening assistant. Score this CV for the position: {job_title}.\n"
            f"Requirements:\n{job_requirements}\n\n"
            "Provide a score (0-100), reasoning, red_flags, and strengths."
        )),
        HumanMessage(content=cv_text),
    ])


def gen_summary(cv_text: str, score: CVScore) -> str:
    response = _get_llm().invoke([
        SystemMessage(content="Write a brief (3-5 sentence) summary for a recruiter reviewing this candidate."),
        HumanMessage(content=(
            f"CV:\n{cv_text}\n\n"
            f"Score: {score.score}/100\n"
            f"Strengths: {', '.join(score.strengths)}\n"
            f"Red flags: {', '.join(score.red_flags)}\n"
            f"Reasoning: {score.reasoning}"
        )),
    ])
    return response.content


def gen_offer(candidate_name: str, job_title: str) -> str:
    response = _get_llm().invoke([
        SystemMessage(content="Draft a professional job offer letter. Keep it concise (1 paragraph + key terms)."),
        HumanMessage(content=f"Candidate: {candidate_name}\nPosition: {job_title}"),
    ])
    return response.content


def gen_rejection(candidate_name: str, reason: str) -> str:
    response = _get_llm().invoke([
        SystemMessage(content="Write a professional, empathetic rejection email. Brief, 2-3 sentences."),
        HumanMessage(content=f"Candidate: {candidate_name}\nReason: {reason}"),
    ])
    return response.content
