from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.schemas.course import CourseVersion, CourseView
from app.services.course_service import course_service
from app.services.research_service import research_service
from learning_db.models import User
from learning_db.session import get_db

router = APIRouter(tags=["courses"])


@router.post("/research-runs/{run_id}/courses", status_code=202)
async def build_course(run_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Start a new course version from a completed research run; poll GET /courses/{id} as it is written."""
    owned = await research_service.owned_run(db, user, run_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Research run not found")
    if owned[0].status != "completed":
        raise HTTPException(status_code=409, detail="Research must finish before a course can be built")
    course, run = await course_service.start_build(db, owned[0])
    background_tasks.add_task(course_service.execute_in_background, course.id)
    return {"id": course.id, "version": course.version, "status": run.status}


@router.get("/research-runs/{run_id}/courses", response_model=list[CourseVersion])
async def list_course_versions(run_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[CourseVersion]:
    if not await research_service.owned_run(db, user, run_id):
        raise HTTPException(status_code=404, detail="Research run not found")
    return await course_service.versions(db, run_id)


@router.get("/courses/{course_id}", response_model=CourseView)
async def get_course(course_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> CourseView:
    owned = await course_service.owned_course(db, user, course_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Course not found")
    course, run, request = owned
    return await course_service.course_view(db, course, run, request.topic)
