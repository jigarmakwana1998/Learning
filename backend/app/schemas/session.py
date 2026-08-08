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


class ToolInvocationResponse(BaseModel):
    tool_name: str
    status: str
    duration_ms: int | None = None
    metadata: dict | None = None
    error: str | None = None
    created_at: datetime


class RunTraceSessionResponse(AgentSessionResponse):
    duration_ms: int | None = None
    tool_invocations: list[ToolInvocationResponse] = Field(default_factory=list)


class LearningRunTraceResponse(BaseModel):
    run_id: str
    sessions: list[RunTraceSessionResponse]


class ResumeSessionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
