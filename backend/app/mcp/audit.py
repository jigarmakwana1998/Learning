from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentEvent


async def record_trace_event(
    db: AsyncSession, *, run_id: str, session_id: str, event_type: str, name: str,
    status: str = "completed", input_payload: dict | None = None, output_payload: dict | None = None,
    metadata: dict | None = None, error: str | None = None, duration_ms: int | None = None,
    prompt_tokens: int | None = None, completion_tokens: int | None = None, total_cost_usd: float | None = None,
    content: str | None = None, created_at: datetime | None = None,
) -> AgentEvent:
    """Single writer for every session event: transcript messages, tool calls, model calls, lifecycle."""
    sequence = ((await db.scalar(select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(AgentEvent.session_id == session_id))) or 0) + 1
    event = AgentEvent(run_id=run_id, session_id=session_id, sequence=sequence, event_type=event_type, name=name, status=status, input_payload=input_payload, output_payload=output_payload, metadata_json=metadata, content=content, error_message=error, duration_ms=duration_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_cost_usd=total_cost_usd)
    if created_at is not None:
        event.created_at = created_at
    db.add(event)
    await db.flush()
    return event


def new_session(run_id: str, agent_name: str, input_payload: dict | None = None) -> AgentEvent:
    return AgentEvent(run_id=run_id, event_type="session", name=agent_name, status="active", input_payload=input_payload)
