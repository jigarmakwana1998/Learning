from datetime import datetime
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentTraceEvent, McpToolInvocation


async def record_trace_event(
    db: AsyncSession, *, run_id: str, session_id: str, event_type: str, name: str,
    status: str = "completed", input_payload: dict | None = None, output_payload: dict | None = None,
    metadata: dict | None = None, error: str | None = None, duration_ms: int | None = None,
    prompt_tokens: int | None = None, completion_tokens: int | None = None, total_cost_usd: float | None = None,
    created_at: datetime | None = None,
) -> AgentTraceEvent:
    sequence = (await db.scalar(select(func.coalesce(func.max(AgentTraceEvent.sequence), 0)).where(AgentTraceEvent.session_id == session_id))) + 1
    event = AgentTraceEvent(run_id=run_id, session_id=session_id, sequence=sequence, event_type=event_type, name=name, status=status, input_payload=input_payload, output_payload=output_payload, metadata_json=metadata, error_message=error, duration_ms=duration_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_cost_usd=total_cost_usd)
    if created_at is not None:
        event.created_at = created_at
    db.add(event)
    await db.flush()
    return event


async def record_tool_invocation(db: AsyncSession, session_id: str, tool_name: str, status: str, metadata: dict | None = None, error: str | None = None, started_at: float | None = None, duration_ms: int | None = None) -> McpToolInvocation:
    if duration_ms is None and started_at is not None:
        duration_ms = int((perf_counter() - started_at) * 1000)
    invocation = McpToolInvocation(session_id=session_id, tool_name=tool_name, status=status, metadata_json=metadata, error_message=error, duration_ms=duration_ms)
    db.add(invocation)
    await db.flush()
    return invocation
