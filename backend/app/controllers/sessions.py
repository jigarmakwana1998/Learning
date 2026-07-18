from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import decrypt
from app.harness import AgentHarness
from app.models.database import AgentRun, AgentSessionRecord, LearningRequest, TranscriptEntryRecord, User
from app.schemas.session import AgentSessionResponse, ResumeSessionRequest, TranscriptEntryResponse

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"])


async def owned_session(db: AsyncSession, user: User, session_id: str) -> AgentSessionRecord:
    query = select(AgentSessionRecord).join(AgentRun, AgentSessionRecord.agent_run_id == AgentRun.id).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).where(AgentSessionRecord.id == session_id)
    if user.role != "admin": query = query.where(LearningRequest.user_id == user.id)
    session = await db.scalar(query)
    if not session: raise HTTPException(status_code=404, detail="Agent session not found")
    return session


async def serialize(db: AsyncSession, session: AgentSessionRecord) -> AgentSessionResponse:
    entries = (await db.scalars(select(TranscriptEntryRecord).where(TranscriptEntryRecord.session_id == session.id).order_by(TranscriptEntryRecord.sequence))).all()
    return AgentSessionResponse(id=session.id, run_id=session.agent_run_id, agent_name=session.agent_name, provider=session.provider, status=session.status, created_at=session.started_at, transcript=[TranscriptEntryResponse(role=item.role, content=decrypt(item.encrypted_content), created_at=item.created_at) for item in entries])


@router.get("/{session_id}", response_model=AgentSessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    return await serialize(db, await owned_session(db, user, session_id))


@router.post("/{session_id}/resume", response_model=AgentSessionResponse)
async def resume_session(session_id: str, request: ResumeSessionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    session = await owned_session(db, user, session_id)
    try: await AgentHarness(session.provider, db).resume_and_run(session.id, request.prompt); await db.commit()
    except (ValueError, RuntimeError) as error: await db.rollback(); raise HTTPException(status_code=422, detail=str(error)) from error
    return await serialize(db, session)


@router.post("/{session_id}/close", response_model=AgentSessionResponse)
async def close_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AgentSessionResponse:
    session = await owned_session(db, user, session_id)
    await AgentHarness(session.provider, db).close(session.id); await db.commit()
    return await serialize(db, session)
