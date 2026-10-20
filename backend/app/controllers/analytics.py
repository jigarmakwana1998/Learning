from sqlalchemy import func, select

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_admin
from app.models.database import AgentEvent, AgentRun, User
from app.schemas.analytics import AnalyticsOverview, RequestListItem, SessionListItem

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
async def overview(db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> AnalyticsOverview:
    async def count(model, *conditions): return int((await db.scalar(select(func.count()).select_from(model).where(*conditions))) or 0)
    is_session = AgentEvent.event_type == "session"
    durations = float((await db.scalar(select(func.avg(AgentEvent.duration_ms)).where(is_session, AgentEvent.duration_ms.is_not(None)))) or 0)
    return AnalyticsOverview(total_users=await count(User), total_requests=await count(AgentRun), completed_runs=await count(AgentRun, AgentRun.status == "completed"), failed_runs=await count(AgentRun, AgentRun.status == "failed"), active_sessions=await count(AgentEvent, is_session, AgentEvent.status == "active"), transcript_entries=await count(AgentEvent, AgentEvent.event_type == "message"), average_session_duration_ms=round(durations, 2))


@router.get("/users")
async def users(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> dict:
    total = int((await db.scalar(select(func.count()).select_from(User))) or 0)
    rows = (await db.scalars(select(User).order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"total": total, "items": [{"id": item.id, "email": item.email, "role": item.role, "created_at": item.created_at} for item in rows]}


@router.get("/requests", response_model=list[RequestListItem])
async def requests(harness: str | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> list[RequestListItem]:
    query = select(AgentRun, User).join(User, AgentRun.user_id == User.id).order_by(AgentRun.started_at.desc()).limit(limit)
    if harness: query = query.where(AgentRun.harness == harness)
    if status: query = query.where(AgentRun.status == status)
    rows = (await db.execute(query)).all()
    return [RequestListItem(id=run.id, user_id=user.id, email=user.email, topic=run.topic, level=run.level, harness=run.harness, run_status=run.status, created_at=run.started_at) for run, user in rows]


@router.get("/sessions", response_model=list[SessionListItem])
async def sessions(harness: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=200), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> list[SessionListItem]:
    query = select(AgentEvent, AgentRun).join(AgentRun, AgentEvent.run_id == AgentRun.id).where(AgentEvent.event_type == "session").order_by(AgentEvent.created_at.desc()).limit(limit)
    if harness: query = query.where(AgentRun.harness == harness)
    if status: query = query.where(AgentEvent.status == status)
    rows = (await db.execute(query)).all()
    return [SessionListItem(id=session.id, agent_name=session.name, harness=run.harness, status=session.status, learning_request_id=run.id, topic=run.topic, duration_ms=session.duration_ms, started_at=session.created_at) for session, run in rows]
