from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.database import AgentRun, LearningRequest, User
from app.schemas.learning import (
    AssignmentSubmissionResponse, EvaluationRequest, EvaluationResponse, LearningProgressRequest,
    LearningProgressResponse, LearningRun, LearningRunRequest, QuizSubmissionRequest,
    QuizSubmissionResponse, WorkSubmissionRequest,
)
from app.services.learning_service import learning_service

router = APIRouter(prefix="/learning-runs", tags=["learning"])


@router.post("", response_model=LearningRun, response_model_exclude_none=True)
async def create_learning_run(request: LearningRunRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> LearningRun:
    try: return await learning_service.create_run(db, user, request)
    except (RuntimeError, ValueError) as error: raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("")
async def list_learning_runs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(AgentRun, LearningRequest).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).where(LearningRequest.user_id == user.id).order_by(AgentRun.started_at.desc()))).all()
    return [{"id": run.id, "topic": request.topic, "provider": run.provider, "status": run.status, "created_at": run.started_at} for run, request in rows]


async def _owned_run_or_404(run_id: str, db: AsyncSession, user: User) -> AgentRun:
    run = await learning_service.owned_run(db, user, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found")
    return run


@router.get("/{run_id}", response_model=LearningRun, response_model_exclude_none=True)
async def get_learning_run(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> LearningRun:
    run = await _owned_run_or_404(run_id, db, user)
    try:
        return learning_service.public_learning_run(learning_service.learning_run(run))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.patch("/{run_id}/progress", response_model=LearningProgressResponse)
async def update_progress(run_id: str, payload: LearningProgressRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> LearningProgressResponse:
    run = await _owned_run_or_404(run_id, db, user)
    try:
        return await learning_service.set_progress(db, user, run, payload.lesson_id, payload.completed)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{run_id}/quiz-submissions", response_model=QuizSubmissionResponse)
async def submit_quiz(run_id: str, payload: QuizSubmissionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> QuizSubmissionResponse:
    run = await _owned_run_or_404(run_id, db, user)
    if payload.quiz_id != "course-quiz":
        raise HTTPException(status_code=422, detail="Unknown quiz for this learning run")
    try:
        return await learning_service.submit_quiz(db, user, run, [(answer.question_id, answer.answer) for answer in payload.answers])
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{run_id}/submissions", response_model=AssignmentSubmissionResponse)
async def submit_work(run_id: str, payload: WorkSubmissionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AssignmentSubmissionResponse:
    run = await _owned_run_or_404(run_id, db, user)
    return await learning_service.submit_work(db, user, run, payload.kind, payload.response)


@router.post("/{run_id}/assignment-submissions", response_model=AssignmentSubmissionResponse)
async def submit_assignment_legacy(run_id: str, payload: WorkSubmissionRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> AssignmentSubmissionResponse:
    """Compatibility endpoint; new clients use /submissions."""
    run = await _owned_run_or_404(run_id, db, user)
    if payload.kind != "assignment":
        raise HTTPException(status_code=422, detail="This endpoint only accepts assignment submissions")
    return await learning_service.submit_work(db, user, run, payload.kind, payload.response)


@router.post("/{run_id}/evaluation", response_model=EvaluationResponse)
async def evaluate_learning(run_id: str, result: EvaluationRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> EvaluationResponse:
    await _owned_run_or_404(run_id, db, user)
    return EvaluationResponse(run_id=run_id, recommendation=learning_service.evaluate(result.score_percent, result.confidence))
