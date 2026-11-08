from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_db.session import get_db
from app.core.dependencies import get_current_user
from app.core.security import decrypt
from learning_db.models import (
    AgentRun, AgentSessionRecord, AgentTraceEvent, Course, LearningRequest, McpToolInvocation, SourcePage,
    TranscriptEntryRecord, User,
)
from app.schemas.learning import LearningGoal, ResearchRun
from app.services.research_service import research_service
from app.schemas.session import (
    LearningRunTraceResponse, RunTraceSessionResponse, ToolInvocationResponse,
    TranscriptEntryResponse,
)

router = APIRouter(prefix="/research-runs", tags=["research"])


@router.post("", status_code=202)
async def create_research_run(goal: LearningGoal, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Start research and return at once; poll GET /{id} for coverage and pages as they arrive."""
    run = await research_service.start_run(db, user, goal)
    background_tasks.add_task(research_service.execute_in_background, run.id, goal)
    return {"id": run.id, "status": run.status}


@router.get("")
async def list_research_runs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(AgentRun, LearningRequest).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).where(LearningRequest.user_id == user.id, AgentRun.id.not_in(select(Course.id))).order_by(AgentRun.started_at.desc()))).all()
    return [{"id": run.id, "topic": request.topic, "harness": run.harness, "status": run.status, "created_at": run.started_at} for run, request in rows]


async def _owned_run_or_404(run_id: str, db: AsyncSession, user: User) -> tuple[AgentRun, LearningRequest]:
    owned = await research_service.owned_run(db, user, run_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Research run not found")
    return owned


@router.get("/{run_id}/activity")
async def research_activity(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    await _owned_run_or_404(run_id, db, user)
    sessions = (await db.scalars(select(AgentSessionRecord).where(AgentSessionRecord.agent_run_id == run_id).order_by(AgentSessionRecord.started_at))).all()
    sources = (await db.scalars(select(SourcePage).where(SourcePage.research_run_id == run_id))).all()
    source_text = {source.url: source.text for source in sources}
    items = []
    for session in sessions:
        events = (await db.scalars(select(AgentTraceEvent).where(AgentTraceEvent.session_id == session.id, AgentTraceEvent.name.in_(["browser_search", "browser_read"]), AgentTraceEvent.output_payload.is_not(None)).order_by(AgentTraceEvent.created_at))).all()
        activity = [{"tool": event.name, "input": event.input_payload or {}, "output": event.output_payload or {}} for event in events]
        if not activity:
            previous = (await db.scalars(select(McpToolInvocation).where(McpToolInvocation.session_id == session.id, McpToolInvocation.tool_name.in_(["browser_search", "browser_read"])).order_by(McpToolInvocation.created_at))).all()
            activity = [{"tool": event.tool_name, "input": (event.metadata_json or {}).get("input", {}), "output": {"results": (event.metadata_json or {}).get("results", [])}} for event in previous]
            for entry in activity:
                if entry["tool"] == "browser_read":
                    for page in entry["output"]["results"]:
                        if page.get("url") in source_text:
                            page["content"] = source_text[page["url"]]
        items.append({"id": session.id, "agent_name": session.agent_name, "status": session.status, "output": session.output_payload, "activity": activity})
    return {"run_id": run_id, "sessions": items}


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


@router.get("/{run_id}", response_model=ResearchRun)
async def get_research_run(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> ResearchRun:
    run, request = await _owned_run_or_404(run_id, db, user)
    return research_service.research_run(run, request.topic)
