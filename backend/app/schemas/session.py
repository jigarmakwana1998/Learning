from datetime import datetime
from pydantic import BaseModel, Field


class TranscriptEntryResponse(BaseModel):
    role: str
    content: str
    created_at: datetime


class AgentSessionResponse(BaseModel):
    id: str
    agent_name: str
    provider: str
    status: str
    created_at: datetime
    transcript: list[TranscriptEntryResponse]
    run_id: str


class ResumeSessionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
