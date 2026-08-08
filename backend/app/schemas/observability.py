from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TraceEventResponse(BaseModel):
    id: str
    session_id: str
    sequence: int
    event_type: str
    name: str
    status: str
    input_payload: dict[str, Any] | None
    output_payload: dict[str, Any] | None
    metadata: dict[str, Any] | None
    error_message: str | None
    duration_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_cost_usd: float | None
    created_at: datetime


class TraceRunListItem(BaseModel):
    id: str
    topic: str
    harness: str
    status: str
    started_at: datetime
    event_count: int
    total_cost_usd: float


class TraceRunResponse(TraceRunListItem):
    sessions: list[dict[str, str]]
    events: list[TraceEventResponse]
