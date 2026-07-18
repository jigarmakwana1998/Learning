from datetime import datetime

from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    total_users: int
    total_requests: int
    completed_runs: int
    failed_runs: int
    active_sessions: int
    transcript_entries: int
    average_session_duration_ms: float


class RequestListItem(BaseModel):
    id: str
    user_id: str
    email: str
    topic: str
    level: str
    provider: str | None
    run_status: str | None
    created_at: datetime


class SessionListItem(BaseModel):
    id: str
    agent_name: str
    provider: str
    status: str
    learning_request_id: str
    topic: str
    duration_ms: int | None
    started_at: datetime
