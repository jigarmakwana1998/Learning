import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import course_builder
from app.harness import AgentHarness
from app.harness.deep_agents import AgentEventCollector
from app.schemas.course import CourseSource, CourseVersion, CourseView
from app.schemas.learning import LearningGoal
from course_mcp.course import Chapter, check
from learning_db.models import AgentRun, Course, LearningRequest, SourcePage, User
from learning_db.session import SessionLocal

logger = logging.getLogger(__name__)


class CourseService:
    course_tools = staticmethod(course_builder.course_tools)
    read_pages = staticmethod(course_builder.read_pages)

    def __init__(self) -> None:
        # ponytail: the activity line of running builds lives in this process (one API worker).
        self.live: dict[str, AgentEventCollector] = {}

    async def start_build(self, db: AsyncSession, research: AgentRun) -> tuple[Course, AgentRun]:
        """A new course version for a completed research run; every build is kept."""
        version = (await db.scalar(select(func.max(Course.version)).where(Course.research_run_id == research.id)) or 0) + 1
        run = AgentRun(learning_request_id=research.learning_request_id, harness="deep-agents")
        db.add(run)
        await db.flush()
        course = Course(id=run.id, research_run_id=research.id, version=version, chapters=[], sections={})
        db.add(course)
        await db.commit()
        return course, run

    async def execute_in_background(self, course_id: str) -> None:
        # ponytail: in-process task, lost on restart (startup marks it failed); move to a job queue to scale out.
        async with SessionLocal() as db:
            try:
                await self.execute_build(db, course_id)
            except Exception:
                logger.exception("course build %s failed", course_id)

    async def execute_build(self, db: AsyncSession, course_id: str) -> None:
        run, course = await db.get(AgentRun, course_id), await db.get(Course, course_id)
        research = await db.get(AgentRun, course.research_run_id)
        request = await db.get(LearningRequest, run.learning_request_id)
        collector = self.live[course_id] = AgentEventCollector()
        error: str | None = "Course build failed"
        gaps: list[str] = []
        try:
            await self._snapshot_sources(db, research)
            async with self.course_tools(course_id) as tools:
                await AgentHarness(run.harness, db).start_and_run(
                    run.id,
                    course_builder.NAME,
                    course_builder.task(LearningGoal.model_validate(request, from_attributes=True)),
                    system_prompt=course_builder.SYSTEM_PROMPT,
                    tools=tools,
                    collector=collector,
                    skills_dir=course_builder.SKILLS_DIR,
                )
            await db.refresh(course)
            if not course.sections:
                raise ValueError("The course builder wrote no sections.")
            coverage = research.result["coverage"]
            untaught = check([Chapter(**c) for c in course.chapters], course.sections, [c["id"] for c in coverage])
            gaps = [item["question"] for item in coverage if item["id"] in untaught["untaught"]]
            error = None
        except (RuntimeError, ValueError) as failure:
            error = str(failure)
            raise
        finally:
            run.status = "failed" if error else "completed"
            run.result = {"error": error, "gaps": gaps}
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            self.live.pop(course_id, None)

    async def _snapshot_sources(self, db: AsyncSession, research: AgentRun) -> None:
        """Fetch the full text of the research run's pages once; later versions cite the same text."""
        # ponytail: two first builds started together both fetch, and one fails on the unique constraint.
        if await db.scalar(select(SourcePage.id).where(SourcePage.research_run_id == research.id).limit(1)):
            return
        pages = research.result["pages"]
        texts = await self.read_pages([page["url"] for page in pages])
        readable = [page for page in pages if texts.get(page["url"])]
        if not readable:
            raise RuntimeError("None of the researched pages could be read again.")
        db.add_all(
            SourcePage(research_run_id=research.id, position=n, url=page["url"], title=page["title"], text=texts[page["url"]])
            for n, page in enumerate(readable, 1)
        )
        await db.commit()

    async def owned_course(self, db: AsyncSession, user: User, course_id: str) -> tuple[Course, AgentRun, LearningRequest] | None:
        row = (
            await db.execute(
                select(Course, AgentRun, LearningRequest)
                .join(AgentRun, Course.id == AgentRun.id)
                .join(LearningRequest)
                .where(Course.id == course_id, LearningRequest.user_id == user.id)
            )
        ).first()
        return (row[0], row[1], row[2]) if row else None

    async def versions(self, db: AsyncSession, research_run_id: str) -> list[CourseVersion]:
        rows = (
            await db.execute(
                select(Course, AgentRun)
                .join(AgentRun, Course.id == AgentRun.id)
                .where(Course.research_run_id == research_run_id)
                .order_by(Course.version.desc())
            )
        ).all()
        return [CourseVersion(id=c.id, version=c.version, status=r.status, created_at=r.started_at) for c, r in rows]

    async def course_view(self, db: AsyncSession, course: Course, run: AgentRun, topic: str) -> CourseView:
        sources = (
            await db.scalars(
                select(SourcePage).where(SourcePage.research_run_id == course.research_run_id).order_by(SourcePage.position)
            )
        ).all()
        collector = self.live.get(course.id)
        return CourseView(
            id=course.id,
            version=course.version,
            status=run.status,
            created_at=run.started_at,
            research_run_id=course.research_run_id,
            topic=topic,
            activity=collector.activity if collector else None,
            chapters=course.chapters,
            sections=course.sections,
            sources=[CourseSource(id=f"s{page.position}", url=page.url, title=page.title) for page in sources],
            **(run.result or {}),
        )


course_service = CourseService()
