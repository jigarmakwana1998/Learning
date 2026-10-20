from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.database import AgentEvent, AgentRun, User
from app.schemas.observability import TraceEventResponse, TraceRunListItem, TraceRunResponse

router = APIRouter(prefix="/observability", tags=["observability"])
# Sessions and transcript messages share agent_events but are not trace events.
TRACE_EVENT = AgentEvent.event_type.not_in(("session", "message"))


def run_scope(user: User):
    query = select(AgentRun)
    return query if user.role == "admin" else query.where(AgentRun.user_id == user.id)


@router.get("/runs", response_model=list[TraceRunListItem])
async def list_traced_runs(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[TraceRunListItem]:
    runs = (await db.scalars(run_scope(user).order_by(AgentRun.started_at.desc()).limit(limit))).all()
    totals = {
        run_id: (count, cost)
        for run_id, count, cost in await db.execute(
            select(AgentEvent.run_id, func.count(), func.coalesce(func.sum(AgentEvent.total_cost_usd), 0))
            .where(AgentEvent.run_id.in_([run.id for run in runs]), TRACE_EVENT)
            .group_by(AgentEvent.run_id)
        )
    }
    return [TraceRunListItem(id=run.id, topic=run.topic, harness=run.harness, status=run.status, started_at=run.started_at, event_count=int(totals.get(run.id, (0, 0))[0]), total_cost_usd=float(totals.get(run.id, (0, 0))[1])) for run in runs]


@router.get("/runs/{run_id}", response_model=TraceRunResponse)
async def get_traced_run(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> TraceRunResponse:
    run = await db.scalar(run_scope(user).where(AgentRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    rows = (await db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id, AgentEvent.event_type != "message").order_by(AgentEvent.created_at, AgentEvent.sequence))).all()
    sessions = [item for item in rows if item.event_type == "session"]
    events = [item for item in rows if item.event_type != "session"]
    return TraceRunResponse(
        id=run.id, topic=run.topic, harness=run.harness, status=run.status, started_at=run.started_at,
        event_count=len(events), total_cost_usd=float(sum(event.total_cost_usd or 0 for event in events)),
        sessions=[{"id": item.id, "agent_name": item.name, "status": item.status} for item in sessions],
        events=[TraceEventResponse(id=item.id, session_id=item.session_id, sequence=item.sequence, event_type=item.event_type, name=item.name, status=item.status, input_payload=item.input_payload, output_payload=item.output_payload, metadata=item.metadata_json, error_message=item.error_message, duration_ms=item.duration_ms, prompt_tokens=item.prompt_tokens, completion_tokens=item.completion_tokens, total_cost_usd=item.total_cost_usd, created_at=item.created_at) for item in events],
    )
