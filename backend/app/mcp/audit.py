from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import McpToolInvocation


async def record_tool_invocation(db: AsyncSession, session_id: str, tool_name: str, status: str, metadata: dict | None = None, error: str | None = None, started_at: float | None = None, duration_ms: int | None = None) -> McpToolInvocation:
    if duration_ms is None and started_at is not None:
        duration_ms = int((perf_counter() - started_at) * 1000)
    invocation = McpToolInvocation(session_id=session_id, tool_name=tool_name, status=status, metadata_json=metadata, error_message=error, duration_ms=duration_ms)
    db.add(invocation)
    await db.flush()
    return invocation
