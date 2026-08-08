from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.database import AgentRun, AgentSessionRecord, AgentTraceEvent, LearningRequest, User
from app.schemas.observability import TraceEventResponse, TraceRunListItem, TraceRunResponse

router = APIRouter(prefix="/observability", tags=["observability"])


def run_scope(user: User):
    query = select(AgentRun, LearningRequest).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id)
    return query if user.role == "admin" else query.where(LearningRequest.user_id == user.id)


@router.get("/runs", response_model=list[TraceRunListItem])
async def list_traced_runs(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[TraceRunListItem]:
    rows = (await db.execute(run_scope(user).order_by(AgentRun.started_at.desc()).limit(limit))).all()
    result = []
    for run, request in rows:
        event_count = int((await db.scalar(select(func.count()).select_from(AgentTraceEvent).where(AgentTraceEvent.run_id == run.id))) or 0)
        cost = float((await db.scalar(select(func.coalesce(func.sum(AgentTraceEvent.total_cost_usd), 0)).where(AgentTraceEvent.run_id == run.id))) or 0)
        result.append(TraceRunListItem(id=run.id, topic=request.topic, harness=run.harness, status=run.status, started_at=run.started_at, event_count=event_count, total_cost_usd=cost))
    return result


@router.get("/runs/{run_id}", response_model=TraceRunResponse)
async def get_traced_run(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> TraceRunResponse:
    row = (await db.execute(run_scope(user).where(AgentRun.id == run_id))).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    run, request = row
    events = (await db.scalars(select(AgentTraceEvent).where(AgentTraceEvent.run_id == run.id).order_by(AgentTraceEvent.created_at, AgentTraceEvent.sequence))).all()
    sessions = (await db.scalars(select(AgentSessionRecord).where(AgentSessionRecord.agent_run_id == run.id).order_by(AgentSessionRecord.started_at))).all()
    return TraceRunResponse(
        id=run.id, topic=request.topic, harness=run.harness, status=run.status, started_at=run.started_at,
        event_count=len(events), total_cost_usd=float(sum(event.total_cost_usd or 0 for event in events)),
        sessions=[{"id": item.id, "agent_name": item.agent_name, "status": item.status} for item in sessions],
        events=[TraceEventResponse(id=item.id, session_id=item.session_id, sequence=item.sequence, event_type=item.event_type, name=item.name, status=item.status, input_payload=item.input_payload, output_payload=item.output_payload, metadata=item.metadata_json, error_message=item.error_message, duration_ms=item.duration_ms, prompt_tokens=item.prompt_tokens, completion_tokens=item.completion_tokens, total_cost_usd=item.total_cost_usd, created_at=item.created_at) for item in events],
    )
