import os

import instructor
from openai import OpenAI

from src.schemas import CandidateContact, CVScore

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = instructor.from_openai(OpenAI(api_key=os.environ.get("OPENAI_API_KEY")))
    return _client


MODEL = "gpt-4o-mini"


def parse_cv_contact(cv_text: str) -> CandidateContact:
    return _get_client().chat.completions.create(
        model=MODEL,
        response_model=CandidateContact,
        max_retries=2,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract contact information from this CV. "
                    "Return the candidate's name and any contact details you find. "
                    "Fields: name, email, phone, telegram, linkedin. "
                    "Set fields to null if not found in the text."
                ),
            },
            {"role": "user", "content": cv_text},
        ],
    )


def score_cv(cv_text: str, job_title: str, job_requirements: str) -> CVScore:
    return _get_client().chat.completions.create(
        model=MODEL,
        response_model=CVScore,
        max_retries=2,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are an HR screening assistant. Score this CV for the position: {job_title}.\n"
                    f"Requirements:\n{job_requirements}\n\n"
                    "Provide a score (0-100), reasoning, red_flags, and strengths."
                ),
            },
            {"role": "user", "content": cv_text},
        ],
    )


def gen_summary(cv_text: str, score: CVScore) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        response_model=None,
        messages=[
            {
                "role": "system",
                "content": "Write a brief (3-5 sentence) summary for a recruiter reviewing this candidate.",
            },
            {
                "role": "user",
                "content": (
                    f"CV:\n{cv_text}\n\n"
                    f"Score: {score.score}/100\n"
                    f"Strengths: {', '.join(score.strengths)}\n"
                    f"Red flags: {', '.join(score.red_flags)}\n"
                    f"Reasoning: {score.reasoning}"
                ),
            },
        ],
    )
    return resp.choices[0].message.content


def gen_offer(candidate_name: str, job_title: str) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        response_model=None,
        messages=[
            {
                "role": "system",
                "content": "Draft a professional job offer letter. Keep it concise (1 paragraph + key terms).",
            },
            {
                "role": "user",
                "content": f"Candidate: {candidate_name}\nPosition: {job_title}",
            },
        ],
    )
    return resp.choices[0].message.content


def gen_rejection(candidate_name: str, reason: str) -> str:
    resp = _get_client().chat.completions.create(
        model=MODEL,
        response_model=None,
        messages=[
            {
                "role": "system",
                "content": "Write a professional, empathetic rejection email. Brief, 2-3 sentences.",
            },
            {
                "role": "user",
                "content": f"Candidate: {candidate_name}\nReason: {reason}",
            },
        ],
    )
    return resp.choices[0].message.content
