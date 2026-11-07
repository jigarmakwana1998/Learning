import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import researcher
from app.harness import AgentHarness
from app.harness.deep_agents import AgentEventCollector
from app.schemas.learning import CoverageItem, LearningGoal, ResearchRun, SavedPage
from learning_db.models import AgentRun, Course, LearningRequest, User
from learning_db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass
class Progress:
    coverage: list[CoverageItem] = field(default_factory=list)
    pages: list[SavedPage] = field(default_factory=list)
    collector: AgentEventCollector = field(default_factory=AgentEventCollector)


class ResearchService:
    browser_tools = staticmethod(researcher.browser_tools)

    def __init__(self) -> None:
        # ponytail: progress of running runs lives in this process (one API worker);
        # move it to the database if the API scales out.
        self.live: dict[str, Progress] = {}

    async def start_run(self, db: AsyncSession, user: User, goal: LearningGoal) -> AgentRun:
        """Persist a running run so callers can return its id before research finishes."""
        request = LearningRequest(user_id=user.id, **goal.model_dump())
        db.add(request)
        await db.flush()
        run = AgentRun(learning_request_id=request.id, harness="deep-agents")
        db.add(run)
        await db.commit()
        return run

    async def execute_in_background(self, run_id: str, goal: LearningGoal) -> None:
        # ponytail: in-process task, lost on restart (startup marks it failed);
        # move to a job queue if runs must survive restarts or scale out.
        async with SessionLocal() as db:
            try:
                await self.execute_run(db, await db.get(AgentRun, run_id), goal)
            except Exception:
                logger.exception("research run %s failed", run_id)

    async def execute_run(self, db: AsyncSession, run: AgentRun, goal: LearningGoal) -> None:
        progress = self.live[run.id] = Progress()
        tools = researcher.progress_tools(progress.coverage, progress.pages, lambda: progress.collector.visited_urls)
        error: str | None = "Research failed"
        try:
            async with self.browser_tools() as browser:
                await AgentHarness(run.harness, db).start_and_run(
                    run.id,
                    researcher.NAME,
                    researcher.task(goal),
                    system_prompt=researcher.SYSTEM_PROMPT,
                    tools=[*browser, *tools],
                    collector=progress.collector,
                    skills_dir=researcher.SKILLS_DIR,
                )
            if not progress.pages:
                raise ValueError("Research found no pages for this topic.")
            error = None
        except (RuntimeError, ValueError) as failure:
            error = str(failure)
            raise
        finally:
            run.status = "failed" if error else "completed"
            run.result = {
                "coverage": [item.model_dump() for item in progress.coverage],
                "pages": [page.model_dump() for page in progress.pages],
                "error": error,
            }
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            self.live.pop(run.id, None)

    async def owned_run(self, db: AsyncSession, user: User, run_id: str) -> tuple[AgentRun, LearningRequest] | None:
        row = (
            await db.execute(
                select(AgentRun, LearningRequest)
                .join(LearningRequest)
                .where(AgentRun.id == run_id, LearningRequest.user_id == user.id, AgentRun.id.not_in(select(Course.id)))
            )
        ).first()
        return (row[0], row[1]) if row else None

    def research_run(self, run: AgentRun, topic: str) -> ResearchRun:
        if progress := self.live.get(run.id):
            return ResearchRun(
                id=run.id,
                topic=topic,
                status=run.status,
                activity=progress.collector.activity,
                coverage=progress.coverage,
                pages=progress.pages,
            )
        return ResearchRun(id=run.id, topic=topic, status=run.status, **(run.result or {}))


research_service = ResearchService()
