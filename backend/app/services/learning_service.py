from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import ExaminerAgent, PlannerAgent, ResearcherAgent
from app.core.config import get_settings
from app.harness import AgentHarness
from app.models.database import AgentRun, LearningRequest, SystemSetting, User
from app.schemas.learning import Assessment, CurriculumModule, LearningGoal, LearningRun, LearningRunRequest, ResearchBrief, Source


class LearningService:
    async def create_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> LearningRun:
        configured = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
        provider = configured.value if configured else get_settings().agent_provider
        if provider not in {"mock", "codex", "gemini-cli", "antigravity-cli"}: raise ValueError("Unsupported agent provider")
        goal = LearningGoal.model_validate(request)
        learning_request = LearningRequest(user_id=user.id, topic=goal.topic, level=goal.level, hours_per_week=goal.hours_per_week, weeks=goal.weeks)
        db.add(learning_request); await db.flush()
        run = AgentRun(learning_request_id=learning_request.id, provider=provider)
        db.add(run); await db.flush()
        harness = AgentHarness(provider, db)
        researcher, planner, examiner = ResearcherAgent(), PlannerAgent(), ExaminerAgent()
        try:
            research_session, research_output = await harness.start_and_run(run.id, researcher.name, researcher.build_prompt(goal))
            if provider == "mock":
                planner_session, _ = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, {"research": "local placeholder"}))
                examiner_session, _ = await harness.start_and_run(run.id, examiner.name, examiner.build_prompt(goal, {"curriculum": "local placeholder"}))
                result = self._mock_run(goal, provider, {"Researcher": research_session.id, "Planner": planner_session.id, "Examiner": examiner_session.id})
            else:
                research = ResearchBrief.model_validate(research_output)
                planner_session, planner_output = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, research.model_dump()))
                curriculum = [CurriculumModule.model_validate(item) for item in planner_output["curriculum"]]
                examiner_session, examiner_output = await harness.start_and_run(run.id, examiner.name, examiner.build_prompt(goal, {"curriculum": [item.model_dump() for item in curriculum]}))
                result = LearningRun(id=run.id, provider=provider, research=research, curriculum=curriculum, assessment=Assessment.model_validate(examiner_output), sessions={"Researcher": research_session.id, "Planner": planner_session.id, "Examiner": examiner_session.id})
            result.id = run.id
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return result
        except Exception:
            run.status, run.completed_at = "failed", datetime.now(timezone.utc)
            await db.commit()
            raise

    def _mock_run(self, goal: LearningGoal, provider: str, sessions: dict[str, str]) -> LearningRun:
        source = Source(title=f"Official {goal.topic} documentation", url="https://www.google.com/search?q=" + goal.topic.replace(" ", "+") + "+official+documentation", kind="documentation", rationale="Local-mode placeholder; a configured researcher replaces it with vetted sources.")
        curriculum = [CurriculumModule(week=week, title=f"{goal.topic}: {'Foundations' if week == 1 else 'Applied practice'}", outcomes=[f"Demonstrate a {goal.level} {goal.topic} skill"], source_urls=[source.url]) for week in range(1, goal.weeks + 1)]
        assessment = Assessment(quiz=[f"Explain a core {goal.topic} concept in your own words.", f"When would you use this {goal.topic} technique?"], assignment=f"Build a small {goal.topic} exercise using this week's concepts.", project=f"Complete a portfolio-ready {goal.topic} project by week {goal.weeks}.")
        return LearningRun(id="", provider=provider, research=ResearchBrief(topic=goal.topic, sources=[source]), curriculum=curriculum, assessment=assessment, sessions=sessions)

    @staticmethod
    def evaluate(score_percent: int, confidence: str) -> str:
        if score_percent < 60 or confidence == "low": return "Review the prerequisite module and add one guided practice assignment before advancing."
        if score_percent >= 85 and confidence == "high": return "Skip the next review block and add an advanced applied project milestone."
        return "Continue with the current sequence and retain the planned practice assignment."


learning_service = LearningService()
