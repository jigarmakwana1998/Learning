import asyncio
import logging
from datetime import UTC, datetime

from app.agents import course_builder, researcher, writer
from app.harness import AgentHarness
from app.harness.deep_agents import AgentEventCollector
from app.schemas.course import CourseSource, CourseVersion, CourseView
from app.schemas.learning import LearningGoal, SavedPage
from course_mcp.course import Chapter, check
from langchain_core.tools import StructuredTool
from learning_db.models import AgentRun, Course, LearningRequest, SourcePage, User
from learning_db.session import SessionLocal
from learning_db.sources import course_sources
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CourseService:
    course_tools = staticmethod(course_builder.course_tools)
    read_pages = staticmethod(course_builder.read_pages)
    browser_tools = staticmethod(researcher.browser_tools)

    def __init__(self) -> None:
        # ponytail: the activity line of running builds lives in this process (one API worker).
        self.live: dict[str, AgentEventCollector] = {}

    async def start_build(self, db: AsyncSession, research: AgentRun) -> tuple[Course, AgentRun]:
        """A new course version for a completed research run; every build is kept."""
        version = (
            await db.scalar(select(func.max(Course.version)).where(Course.research_run_id == research.id)) or 0
        ) + 1
        run = AgentRun(
            learning_request_id=research.learning_request_id, harness="deep-agents", result={"source_snapshot": True}
        )
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
            await self._snapshot_sources(db, research, course_id)
            async with self.course_tools(course_id) as tools, self.browser_tools() as browser:
                by_name = {tool.name: tool for tool in tools}
                reading = [by_name[name] for name in ("list_sources", "read_source", "search_sources", "read_section")]
                await AgentHarness(run.harness, db).start_and_run(
                    run.id,
                    course_builder.NAME,
                    course_builder.task(LearningGoal.model_validate(request, from_attributes=True)),
                    system_prompt=course_builder.SYSTEM_PROMPT,
                    tools=[*reading, by_name["set_outline"], by_name["check_course"]],
                    subagents=[
                        {
                            "name": "researcher",
                            "description": "Find and save sources for focused topic questions or section gaps.",
                            "system_prompt": researcher.DELEGATED_PROMPT,
                            "skills_dir": researcher.SKILLS_DIR,
                            "tools": [*browser, by_name["list_sources"], self._save_source_tool(course_id, collector)],
                        },
                        {
                            "name": writer.NAME,
                            "description": "Write or revise chapters and sections, returning research gaps.",
                            "system_prompt": writer.SYSTEM_PROMPT,
                            "skills_dir": writer.SKILLS_DIR,
                            "tools": [*reading, by_name["write_section"]],
                        },
                    ],
                    collector=collector,
                    skills_dir=course_builder.SKILLS_DIR,
                )
            await db.refresh(course)
            coverage = (research.result or {}).get("coverage", [])
            chapters = [Chapter(**c) for c in course.chapters]
            left = check(chapters, course.sections, [c["id"] for c in coverage])
            titles = {s.id: s.title or s.id for chapter in chapters for s in chapter.sections}
            gaps = [f"Section not written: {titles[s]}" for s in left["unwritten"]]
            gaps += [item["question"] for item in coverage if item["id"] in left["untaught"]]
            error = None
        except Exception as failure:
            error = str(failure)
            raise
        finally:
            run.status = "failed" if error else "completed"
            run.result = {**(run.result or {}), "error": error, "gaps": gaps}
            run.completed_at = datetime.now(UTC)
            await db.commit()
            self.live.pop(course_id, None)

    async def _snapshot_sources(self, db: AsyncSession, research: AgentRun, course_id: str) -> None:
        """Reuse initial research text, then give this course its own appendable source library."""
        query = select(SourcePage).where(SourcePage.research_run_id == research.id).order_by(SourcePage.position)
        sources = list((await db.scalars(query)).all())
        if not sources:
            pages = (research.result or {}).get("pages", [])
            try:
                texts = await self.read_pages([page["url"] for page in pages]) if pages else {}
            except (RuntimeError, ValueError) as failure:
                logger.warning("Initial sources unavailable; Researcher can find replacements: %s", failure)
                texts = {}
            try:
                async with db.begin_nested():
                    db.add_all(
                        SourcePage(
                            research_run_id=research.id,
                            position=n,
                            url=page["url"],
                            title=page.get("title", ""),
                            text=texts[page["url"]],
                        )
                        for n, page in enumerate((page for page in pages if texts.get(page["url"])), 1)
                    )
                    await db.flush()
            except IntegrityError:
                # Another first build may have saved these same initial snapshots.
                pass
            sources = list((await db.scalars(query)).all())
        db.add_all(
            SourcePage(
                research_run_id=course_id,
                position=page.position,
                url=page.url,
                title=page.title,
                text=page.text,
                fetched_at=page.fetched_at,
            )
            for page in sources
        )
        await db.commit()

    @staticmethod
    def _save_source_tool(course_id: str, collector: AgentEventCollector) -> StructuredTool:
        writes = asyncio.Lock()

        async def save_page(**fields) -> str:
            """Save a selected source to this course, capturing text already returned by browser_read."""
            page = SavedPage(**fields)
            captured = collector.read_pages.get(page.url, {})
            text = captured.get("content", "")
            async with writes, SessionLocal() as db:
                saved = await db.scalar(
                    select(SourcePage).where(
                        SourcePage.research_run_id == course_id,
                        SourcePage.url == page.url,
                    )
                )
                if saved is None:
                    position = (
                        await db.scalar(
                            select(func.max(SourcePage.position)).where(
                                SourcePage.research_run_id == course_id,
                            )
                        )
                        or 0
                    ) + 1
                    saved = SourcePage(
                        research_run_id=course_id,
                        position=position,
                        url=page.url,
                        title=page.title or captured.get("title") or page.url,
                        text=text,
                    )
                    db.add(saved)
                elif not saved.text:
                    saved.text = text
                await db.commit()
                note = (
                    " Page text is not available yet; browser_read then save_page can add it." if not saved.text else ""
                )
                return f"Saved s{saved.position}: {saved.url}.{note}"

        return StructuredTool.from_function(
            coroutine=save_page, args_schema=SavedPage, handle_validation_error=True, handle_tool_error=True
        )

    async def owned_course(
        self, db: AsyncSession, user: User, course_id: str
    ) -> tuple[Course, AgentRun, LearningRequest] | None:
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
        sources = await course_sources(db, course)
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
