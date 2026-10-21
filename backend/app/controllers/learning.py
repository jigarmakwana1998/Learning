from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_db.session import get_db
from app.core.dependencies import get_current_user
from app.core.security import decrypt
from learning_db.models import (
    AgentRun, AgentSessionRecord, LearningRequest, McpToolInvocation,
    TranscriptEntryRecord, User,
)
from app.schemas.learning import LearningRun, LearningRunRequest
from app.services.learning_service import learning_service
from app.schemas.session import (
    LearningRunTraceResponse, RunTraceSessionResponse, ToolInvocationResponse,
    TranscriptEntryResponse,
)

router = APIRouter(prefix="/learning-runs", tags=["learning"])


@router.post("", status_code=202)
async def create_learning_run(request: LearningRunRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Start generation and return at once; poll /{id}/status, then GET /{id}."""
    run = await learning_service.start_run(db, user, request)
    background_tasks.add_task(learning_service.execute_in_background, run.id, request)
    return {"id": run.id, "status": run.status}


@router.get("/{run_id}/status")
async def get_learning_run_status(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    run = await _owned_run_or_404(run_id, db, user)
    error = (run.result or {}).get("error") if run.status == "failed" else None
    return {"id": run.id, "status": run.status, "error": error}


@router.get("")
async def list_learning_runs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(AgentRun, LearningRequest).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).where(LearningRequest.user_id == user.id).order_by(AgentRun.started_at.desc()))).all()
    return [{"id": run.id, "topic": request.topic, "harness": run.harness, "status": run.status, "created_at": run.started_at} for run, request in rows]


async def _owned_run_or_404(run_id: str, db: AsyncSession, user: User) -> AgentRun:
    run = await learning_service.owned_run(db, user, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found")
    return run


@router.get("/{run_id}/trace", response_model=LearningRunTraceResponse)
async def get_learning_run_trace(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LearningRunTraceResponse:
    await _owned_run_or_404(run_id, db, user)
    sessions = (
        await db.scalars(
            select(AgentSessionRecord)
            .where(AgentSessionRecord.agent_run_id == run_id)
            .order_by(AgentSessionRecord.started_at, AgentSessionRecord.id)
        )
    ).all()
    items: list[RunTraceSessionResponse] = []
    for session in sessions:
        transcript = (
            await db.scalars(
                select(TranscriptEntryRecord)
                .where(TranscriptEntryRecord.session_id == session.id)
                .order_by(TranscriptEntryRecord.sequence, TranscriptEntryRecord.created_at)
            )
        ).all()
        tools = (
            await db.scalars(
                select(McpToolInvocation)
                .where(McpToolInvocation.session_id == session.id)
                .order_by(McpToolInvocation.created_at, McpToolInvocation.id)
            )
        ).all()
        items.append(
            RunTraceSessionResponse(
                id=session.id,
                run_id=run_id,
                agent_name=session.agent_name,
                harness=session.harness,
                status=session.status,
                created_at=session.started_at,
                duration_ms=session.duration_ms,
                transcript=[
                    TranscriptEntryResponse(
                        role=entry.role,
                        content=decrypt(entry.encrypted_content),
                        created_at=entry.created_at,
                    )
                    for entry in transcript
                ],
                tool_invocations=[
                    ToolInvocationResponse(
                        tool_name=tool.tool_name,
                        status=tool.status,
                        duration_ms=tool.duration_ms,
                        metadata=tool.metadata_json,
                        error=tool.error_message,
                        created_at=tool.created_at,
                    )
                    for tool in tools
                ],
            )
        )
    return LearningRunTraceResponse(run_id=run_id, sessions=items)


@router.get("/{run_id}", response_model=LearningRun, response_model_exclude_none=True)
async def get_learning_run(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> LearningRun:
    run = await _owned_run_or_404(run_id, db, user)
    try:
        return learning_service.learning_run(run)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
