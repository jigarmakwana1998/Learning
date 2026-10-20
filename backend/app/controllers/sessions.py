from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import decrypt
from app.harness import AgentHarness
from app.models.database import AgentEvent, AgentRun, User
from app.schemas.session import AgentSessionResponse, ResumeSessionRequest, TranscriptEntryResponse

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"])


async def owned_session(db: AsyncSession, user: User, session_id: str) -> tuple[AgentEvent, AgentRun]:
    query = select(AgentEvent, AgentRun).join(AgentRun, AgentEvent.run_id == AgentRun.id).where(AgentEvent.id == session_id, AgentEvent.event_type == "session")
    if user.role != "admin": query = query.where(AgentRun.user_id == user.id)
    row = (await db.execute(query)).first()
    if not row: raise HTTPException(status_code=404, detail="Agent session not found")
    return row[0], row[1]


async def serialize(db: AsyncSession, session: AgentEvent, run: AgentRun) -> AgentSessionResponse:
    entries = (await db.scalars(select(AgentEvent).where(AgentEvent.session_id == session.id, AgentEvent.event_type == "message").order_by(AgentEvent.sequence))).all()
    return AgentSessionResponse(id=session.id, run_id=session.run_id, agent_name=session.name, harness=run.harness, status=session.status, created_at=session.created_at, transcript=[TranscriptEntryResponse(role=item.name, content=decrypt(item.content), created_at=item.created_at) for item in entries])


@router.get("/{session_id}", response_model=AgentSessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    return await serialize(db, *await owned_session(db, user, session_id))


@router.post("/{session_id}/resume", response_model=AgentSessionResponse)
async def resume_session(session_id: str, request: ResumeSessionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    session, run = await owned_session(db, user, session_id)
    try: await AgentHarness(run.harness, db).resume_and_run(session.id, request.prompt); await db.commit()
    except (ValueError, RuntimeError) as error: await db.rollback(); raise HTTPException(status_code=422, detail=str(error)) from error
    return await serialize(db, session, run)


@router.post("/{session_id}/close", response_model=AgentSessionResponse)
async def close_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    session, run = await owned_session(db, user, session_id)
    await AgentHarness(run.harness, db).close(session.id); await db.commit()
    return await serialize(db, session, run)
