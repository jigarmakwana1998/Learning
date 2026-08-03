from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import ExaminerAgent, PlannerAgent, ResearcherAgent
from app.core.config import get_settings
from app.harness import AgentHarness
from app.models.database import (
    AgentRun, AssignmentSubmissionRecord, LearningRequest, LessonProgressRecord,
    QuizSubmissionRecord, SystemSetting, User,
)
from app.schemas.learning import (
    Assessment, Assignment, AssignmentSubmissionResponse, Course, CurriculumModule,
    LearningGoal, LearningProgressResponse, LearningRun, LearningRunRequest, Lesson,
    QuizQuestionFeedback, QuizSubmissionResponse, ResearchBrief, Source,
)


class LearningService:
    async def create_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> LearningRun:
        configured = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
        provider = configured.value if configured else get_settings().agent_provider
        if provider not in {"mock", "codex", "gemini-cli", "antigravity-cli"}:
            raise ValueError("Unsupported agent provider")
        goal = LearningGoal.model_validate(request)
        learning_request = LearningRequest(user_id=user.id, topic=goal.topic, level=goal.level, hours_per_week=goal.hours_per_week, weeks=goal.weeks)
        db.add(learning_request)
        await db.flush()
        run = AgentRun(learning_request_id=learning_request.id, provider=provider)
        db.add(run)
        await db.flush()
        harness = AgentHarness(provider, db)
        researcher, planner, examiner = ResearcherAgent(), PlannerAgent(), ExaminerAgent()
        try:
            research_session, research_output = await harness.start_and_run(run.id, researcher.name, researcher.build_prompt(goal))
            if provider == "mock":
                planner_session, _ = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, {"research": "local deterministic course"}))
                examiner_session, _ = await harness.start_and_run(run.id, examiner.name, examiner.build_prompt(goal, {"curriculum": "local deterministic course"}))
                result = self._mock_run(goal, provider, {"Researcher": research_session.id, "Planner": planner_session.id, "Examiner": examiner_session.id})
            else:
                research = ResearchBrief.model_validate(research_output)
                planner_session, planner_output = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, research.model_dump()))
                raw_curriculum = [CurriculumModule.model_validate(item) for item in planner_output["curriculum"]]
                curriculum = self._enrich_curriculum(goal, raw_curriculum)
                examiner_session, _ = await harness.start_and_run(run.id, examiner.name, examiner.build_prompt(goal, {"curriculum": [item.model_dump() for item in curriculum]}))
                assessment = self._build_assessment(goal)
                result = LearningRun(
                    id=run.id, provider=provider, research=research, curriculum=curriculum,
                    course=Course(title=f"{goal.topic} learning path", modules=curriculum), assessment=assessment,
                    sessions={"Researcher": research_session.id, "Planner": planner_session.id, "Examiner": examiner_session.id},
                )
            result.id = run.id
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return self.public_learning_run(result)
        except Exception:
            run.status, run.completed_at = "failed", datetime.now(timezone.utc)
            await db.commit()
            raise

    def _mock_run(self, goal: LearningGoal, provider: str, sessions: dict[str, str]) -> LearningRun:
        source = Source(
            title=f"Official {goal.topic} documentation",
            url="https://www.google.com/search?q=" + goal.topic.replace(" ", "+") + "+official+documentation",
            kind="documentation",
            rationale="Start with the official reference, then validate examples against its current version.",
        )
        curriculum = self._enrich_curriculum(goal, [
            CurriculumModule(
                week=week,
                title=self._module_title(goal.topic, week),
                outcomes=self._outcomes(goal.topic, goal.level, week),
                source_urls=[source.url],
            )
            for week in range(1, goal.weeks + 1)
        ])
        assessment = self._build_assessment(goal)
        return LearningRun(
            id="", provider=provider, research=ResearchBrief(topic=goal.topic, sources=[source]),
            curriculum=curriculum, course=Course(title=f"{goal.topic} learning path", modules=curriculum),
            assessment=assessment, sessions=sessions,
        )

    @staticmethod
    def _module_title(topic: str, week: int) -> str:
        phases = ["Foundations and vocabulary", "Core workflow", "Guided practice", "Integration and reflection"]
        return f"{topic}: {phases[min(week - 1, len(phases) - 1)]}"

    @staticmethod
    def _outcomes(topic: str, level: str, week: int) -> list[str]:
        if week == 1:
            return [f"Explain the essential vocabulary of {topic}", f"Set up a repeatable {topic} study and practice environment"]
        if week == 2:
            return [f"Apply a core {topic} workflow to a small example", f"Check work against documentation and expected outcomes"]
        return [f"Complete and explain a {level}-level {topic} practice task", f"Identify one improvement after reviewing evidence from the task"]

    def _enrich_curriculum(self, goal: LearningGoal, curriculum: list[CurriculumModule]) -> list[CurriculumModule]:
        """Make every generated outline usable in the study player, including CLI-agent output."""
        enriched: list[CurriculumModule] = []
        for module in curriculum:
            week = module.week
            lessons = module.lessons or [
                Lesson(
                    id=f"week-{week}-learn",
                    title=f"Learn: {module.title}",
                    objective=module.outcomes[0] if module.outcomes else f"Build a working mental model of {goal.topic}",
                    content=(
                        f"### Focus\nThis lesson turns **{goal.topic}** into a concrete workflow. Read one primary source, "
                        "write down unfamiliar terms, and connect each term to an example.\n\n"
                        "### Study loop\n1. Read a short reference section.\n2. Reproduce its smallest example.\n"
                        "3. Change one input and record what changed.\n4. Explain the result in your own words.\n\n"
                        "### Checkpoint\nYou should be able to state the problem this technique solves, its inputs, and how to verify its output."
                    ),
                    practice=f"Create a one-page {goal.topic} note with three terms, one tiny example, and one question to investigate.",
                    estimated_minutes=max(20, min(90, goal.hours_per_week * 12)),
                ),
                Lesson(
                    id=f"week-{week}-apply",
                    title=f"Apply: {module.title}",
                    objective=module.outcomes[-1] if module.outcomes else f"Practise {goal.topic} with evidence",
                    content=(
                        f"### Deliberate practice\nChoose one small, observable use of **{goal.topic}**. Work in short iterations: "
                        "predict the result, try it, compare the result with your prediction, and capture the evidence.\n\n"
                        "### Reflection\nDescribe one mistake or surprise. Then revise the example once, explaining why the revision is stronger."
                    ),
                    practice=f"Complete a 30-minute {goal.topic} exercise and save the starting point, final result, and a short reflection.",
                    estimated_minutes=max(20, min(90, goal.hours_per_week * 12)),
                ),
            ]
            enriched.append(module.model_copy(update={
                "overview": module.overview or f"Week {week} combines focused study and hands-on {goal.topic} practice.",
                "estimated_hours": module.estimated_hours or max(1, goal.hours_per_week),
                "lessons": lessons,
            }))
        return enriched

    def _build_assessment(self, goal: LearningGoal) -> Assessment:
        questions = []
        for week in range(1, goal.weeks + 1):
            questions.extend([
                {
                    "id": f"week-{week}-q1", "module_week": week,
                    "prompt": f"When beginning a new {goal.topic} task, what is the most reliable first step?",
                    "choices": ["Define the goal, key terms, and a small observable example", "Start with the largest possible project", "Memorize every reference page", "Skip validation until the end"],
                    "correct_answer": "Define the goal, key terms, and a small observable example",
                    "explanation": "A small observable example creates a feedback loop and makes the topic manageable.",
                },
                {
                    "id": f"week-{week}-q2", "module_week": week,
                    "prompt": f"How should you check a {goal.topic} practice result?",
                    "choices": ["Compare it with a documented expectation and explain any difference", "Assume it is right if it looks plausible", "Only ask someone else to verify it", "Change several variables at once"],
                    "correct_answer": "Compare it with a documented expectation and explain any difference",
                    "explanation": "Comparing one result to a known expectation turns practice into evidence-based learning.",
                },
            ])
        quiz_items = [self._quiz_item(item) for item in questions]
        assignment = Assignment(
            title=f"{goal.topic} evidence notebook",
            prompt=f"Build a small {goal.topic} example that demonstrates one course outcome. Include your initial prediction, the steps you followed, evidence of the result, and a reflection.",
            deliverables=["A reproducible example or walkthrough", "A short explanation of the concepts used", "Evidence of the result", "A reflection describing one revision"],
            rubric=["The example has a clear goal and scope", "Concepts are explained accurately", "Evidence supports the claimed result", "Reflection identifies a useful next step"],
        )
        return Assessment(quiz=quiz_items, quiz_items=quiz_items, assignment=assignment, project=f"Complete a portfolio-ready {goal.topic} project by week {goal.weeks}, documenting decisions and validation evidence.")

    @staticmethod
    def _quiz_item(payload: dict):
        from app.schemas.learning import QuizItem
        return QuizItem(**payload)

    async def owned_run(self, db: AsyncSession, user: User, run_id: str) -> AgentRun | None:
        return await db.scalar(select(AgentRun).join(LearningRequest).where(AgentRun.id == run_id, LearningRequest.user_id == user.id))

    @staticmethod
    def learning_run(run: AgentRun) -> LearningRun:
        if not run.result:
            raise ValueError("Learning run has not completed")
        return LearningRun.model_validate(run.result)

    @staticmethod
    def public_learning_run(run: LearningRun) -> LearningRun:
        """Never reveal answer keys before a learner has submitted the quiz."""
        quiz_items = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz_items]
        legacy_quiz = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz]
        assessment = run.assessment.model_copy(update={"quiz_items": quiz_items, "quiz": legacy_quiz})
        return run.model_copy(update={"assessment": assessment})

    async def submit_quiz(self, db: AsyncSession, user: User, run: AgentRun, answers: list[tuple[str, str]]) -> QuizSubmissionResponse:
        course = self.learning_run(run)
        questions = course.assessment.quiz_items or course.assessment.quiz
        by_id = {question.id: question for question in questions}
        supplied = dict(answers)
        if unknown := set(supplied) - set(by_id):
            raise ValueError(f"Unknown quiz question: {sorted(unknown)[0]}")
        feedback = [
            QuizQuestionFeedback(
                question_id=question.id, selected_answer=supplied.get(question.id),
                correct=supplied.get(question.id) == question.correct_answer,
                correct_answer=question.correct_answer or "", explanation=question.explanation or "",
            )
            for question in questions
        ]
        correct_count = sum(item.correct for item in feedback)
        score = round(correct_count * 100 / len(questions)) if questions else 0
        record = QuizSubmissionRecord(
            agent_run_id=run.id, user_id=user.id, answers=supplied, score_percent=score,
            feedback=[item.model_dump(mode="json") for item in feedback],
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return QuizSubmissionResponse(id=record.id, run_id=run.id, score_percent=score, correct_count=correct_count, total_questions=len(questions), feedback=feedback, submitted_at=record.submitted_at)

    async def submit_work(self, db: AsyncSession, user: User, run: AgentRun, kind: str, content: str) -> AssignmentSubmissionResponse:
        course = self.learning_run(run)
        expected = course.assessment.assignment.deliverables if kind == "assignment" else ["A working outcome", "A short decision log", "Validation evidence", "A reflection"]
        word_count = len(content.split())
        status = "accepted" if word_count >= 120 else "needs_revision"
        feedback = [
            f"Submitted {word_count} words for the {kind}.",
            f"To strengthen it, make sure it includes: {expected[0].lower()}.",
            "Add a concrete observation or artifact that lets another learner verify your result.",
        ]
        record = AssignmentSubmissionRecord(agent_run_id=run.id, user_id=user.id, kind=kind, content=content, status=status, feedback=feedback)
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return AssignmentSubmissionResponse(id=record.id, run_id=run.id, kind=kind, content=content, status=status, feedback=feedback, submitted_at=record.submitted_at)

    async def set_progress(self, db: AsyncSession, user: User, run: AgentRun, lesson_id: str, completed: bool) -> LearningProgressResponse:
        course = self.learning_run(run)
        lessons = [lesson for module in (course.course.modules if course.course else course.curriculum) for lesson in module.lessons]
        if lesson_id not in {lesson.id for lesson in lessons}:
            raise ValueError("Unknown lesson for this learning run")
        record = await db.get(LessonProgressRecord, (run.id, user.id, lesson_id))
        if record is None:
            record = LessonProgressRecord(agent_run_id=run.id, user_id=user.id, lesson_id=lesson_id, completed=completed)
            db.add(record)
        else:
            record.completed = completed
        await db.commit()
        completed_lessons = await db.scalar(select(func.count()).select_from(LessonProgressRecord).where(LessonProgressRecord.agent_run_id == run.id, LessonProgressRecord.user_id == user.id, LessonProgressRecord.completed.is_(True)))
        return LearningProgressResponse(run_id=run.id, lesson_id=lesson_id, completed=completed, completed_lessons=completed_lessons or 0, total_lessons=len(lessons))

    @staticmethod
    def evaluate(score_percent: int, confidence: str) -> str:
        if score_percent < 60 or confidence == "low":
            return "Review the prerequisite module and add one guided practice assignment before advancing."
        if score_percent >= 85 and confidence == "high":
            return "Skip the next review block and add an advanced applied project milestone."
        return "Continue with the current sequence and retain the planned practice assignment."


learning_service = LearningService()
