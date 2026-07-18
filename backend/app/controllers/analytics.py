from sqlalchemy import func, select

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_admin
from app.models.database import AgentRun, AgentSessionRecord, LearningRequest, SystemSetting, TranscriptEntryRecord, User
from app.schemas.analytics import AnalyticsOverview, RequestListItem, SessionListItem
from app.schemas.learning import AgentProviderSetting

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/settings/agent-provider", response_model=AgentProviderSetting)
async def get_agent_provider(db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> AgentProviderSetting:
    setting = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
    return AgentProviderSetting(provider=setting.value if setting else "mock")


@router.put("/settings/agent-provider", response_model=AgentProviderSetting)
async def set_agent_provider(payload: AgentProviderSetting, db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> AgentProviderSetting:
    setting = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
    if setting is None:
        db.add(SystemSetting(key="agent_provider", value=payload.provider))
    else:
        setting.value = payload.provider
    await db.commit()
    return payload


@router.get("/overview", response_model=AnalyticsOverview)
async def overview(db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> AnalyticsOverview:
    async def count(model, *conditions): return int((await db.scalar(select(func.count()).select_from(model).where(*conditions))) or 0)
    durations = float((await db.scalar(select(func.avg(AgentSessionRecord.duration_ms)).where(AgentSessionRecord.duration_ms.is_not(None)))) or 0)
    return AnalyticsOverview(total_users=await count(User), total_requests=await count(LearningRequest), completed_runs=await count(AgentRun, AgentRun.status == "completed"), failed_runs=await count(AgentRun, AgentRun.status == "failed"), active_sessions=await count(AgentSessionRecord, AgentSessionRecord.status == "active"), transcript_entries=await count(TranscriptEntryRecord), average_session_duration_ms=round(durations, 2))


@router.get("/users")
async def users(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> dict:
    total = int((await db.scalar(select(func.count()).select_from(User))) or 0)
    rows = (await db.scalars(select(User).order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return {"total": total, "items": [{"id": item.id, "email": item.email, "role": item.role, "created_at": item.created_at} for item in rows]}


@router.get("/requests", response_model=list[RequestListItem])
async def requests(provider: str | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> list[RequestListItem]:
    query = select(LearningRequest, User, AgentRun).join(User, LearningRequest.user_id == User.id).outerjoin(AgentRun, AgentRun.learning_request_id == LearningRequest.id).order_by(LearningRequest.created_at.desc()).limit(limit)
    if provider: query = query.where(AgentRun.provider == provider)
    if status: query = query.where(AgentRun.status == status)
    rows = (await db.execute(query)).all()
    return [RequestListItem(id=request.id, user_id=user.id, email=user.email, topic=request.topic, level=request.level, provider=run.provider if run else None, run_status=run.status if run else None, created_at=request.created_at) for request, user, run in rows]


@router.get("/sessions", response_model=list[SessionListItem])
async def sessions(provider: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=200), db: AsyncSession = Depends(get_db), _: User = Depends(get_admin)) -> list[SessionListItem]:
    query = select(AgentSessionRecord, AgentRun, LearningRequest).join(AgentRun, AgentSessionRecord.agent_run_id == AgentRun.id).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).order_by(AgentSessionRecord.started_at.desc()).limit(limit)
    if provider: query = query.where(AgentSessionRecord.provider == provider)
    if status: query = query.where(AgentSessionRecord.status == status)
    rows = (await db.execute(query)).all()
    return [SessionListItem(id=session.id, agent_name=session.agent_name, provider=session.provider, status=session.status, learning_request_id=request.id, topic=request.topic, duration_ms=session.duration_ms, started_at=session.started_at) for session, _, request in rows]
