from pydantic import BaseModel, Field
from typing import Optional


class CandidateContact(BaseModel):
    name: str = Field(description="Full name of the candidate")
    email: Optional[str] = Field(None, description="Email address if found in CV")
    phone: Optional[str] = Field(None, description="Phone number if found in CV")
    telegram: Optional[str] = Field(None, description="Telegram handle if found in CV")
    linkedin: Optional[str] = Field(None, description="LinkedIn URL if found in CV")


class CVScore(BaseModel):
    score: int = Field(ge=0, le=100, description="Overall score 0-100")
    reasoning: str = Field(description="Brief reasoning for the score")
    red_flags: list[str] = Field(default_factory=list, description="Potential concerns")
    strengths: list[str] = Field(default_factory=list, description="Key strengths")
