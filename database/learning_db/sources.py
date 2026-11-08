"""Read version-specific source snapshots, with compatibility for existing courses."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentRun, Course, SourcePage


async def course_sources(db: AsyncSession, course: Course) -> list[SourcePage]:
    run = await db.get(AgentRun, course.id)
    owner = course.id if (run.result or {}).get("source_snapshot") else course.research_run_id
    return list(
        (
            await db.scalars(
                select(SourcePage).where(SourcePage.research_run_id == owner).order_by(SourcePage.position)
            )
        ).all()
    )
