from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.database import AgentRun, LearningRequest, User
from app.schemas.learning import EvaluationRequest, EvaluationResponse, LearningRun, LearningRunRequest
from app.services.learning_service import learning_service

router = APIRouter(prefix="/learning-runs", tags=["learning"])


@router.post("", response_model=LearningRun)
async def create_learning_run(request: LearningRunRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> LearningRun:
    try: return await learning_service.create_run(db, user, request)
    except (RuntimeError, ValueError) as error: raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("")
async def list_learning_runs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(AgentRun, LearningRequest).join(LearningRequest, AgentRun.learning_request_id == LearningRequest.id).where(LearningRequest.user_id == user.id).order_by(AgentRun.started_at.desc()))).all()
    return [{"id": run.id, "topic": request.topic, "provider": run.provider, "status": run.status, "created_at": run.started_at} for run, request in rows]


@router.post("/{run_id}/evaluation", response_model=EvaluationResponse)
async def evaluate_learning(run_id: str, result: EvaluationRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> EvaluationResponse:
    run = await db.scalar(select(AgentRun).join(LearningRequest).where(AgentRun.id == run_id, LearningRequest.user_id == user.id))
    if not run: raise HTTPException(status_code=404, detail="Learning run not found")
    return EvaluationResponse(run_id=run_id, recommendation=learning_service.evaluate(result.score_percent, result.confidence))
