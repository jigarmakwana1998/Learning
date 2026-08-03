from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentProvider = Literal["mock", "codex", "gemini-cli", "antigravity-cli"]


class LearningGoal(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    hours_per_week: int = Field(default=5, ge=1, le=40)
    weeks: int = Field(default=4, ge=1, le=24)


class LearningRunRequest(LearningGoal):
    pass


class AgentProviderSetting(BaseModel):
    provider: AgentProvider


class Source(BaseModel):
    title: str
    url: str
    kind: Literal["documentation", "paper", "book", "lecture", "article", "repository"]
    rationale: str


class ResearchBrief(BaseModel):
    topic: str
    sources: list[Source]


class CurriculumModule(BaseModel):
    week: int
    title: str
    outcomes: list[str]
    source_urls: list[str]
    overview: str = ""
    estimated_hours: int = Field(default=1, ge=1)
    lessons: list["Lesson"] = Field(default_factory=list)


class Lesson(BaseModel):
    id: str
    title: str
    objective: str
    content: str
    practice: str
    estimated_minutes: int = Field(ge=5, le=240)


class QuizItem(BaseModel):
    id: str
    module_week: int
    prompt: str
    choices: list[str] = Field(min_length=2, max_length=6)
    # These are deliberately omitted from course responses; the durable run payload
    # retains them for server-side grading and submission feedback.
    correct_answer: str | None = None
    explanation: str | None = None


class Assignment(BaseModel):
    title: str
    prompt: str
    deliverables: list[str]
    rubric: list[str]


class Assessment(BaseModel):
    # `quiz` remains for older mobile consumers. New clients should use quiz_items.
    quiz: list[QuizItem] = Field(default_factory=list)
    quiz_items: list[QuizItem] = Field(default_factory=list)
    assignment: Assignment
    project: str


class Course(BaseModel):
    title: str
    modules: list[CurriculumModule]


class LearningRun(BaseModel):
    id: str
    provider: AgentProvider
    research: ResearchBrief
    curriculum: list[CurriculumModule]
    course: Course | None = None
    assessment: Assessment
    sessions: dict[str, str]


class EvaluationRequest(BaseModel):
    score_percent: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]


class EvaluationResponse(BaseModel):
    run_id: str
    recommendation: str


class QuizAnswer(BaseModel):
    question_id: str
    answer: str


class QuizSubmissionRequest(BaseModel):
    quiz_id: str = "course-quiz"
    answers: list[QuizAnswer] = Field(min_length=1)


class QuizQuestionFeedback(BaseModel):
    question_id: str
    correct: bool
    selected_answer: str | None
    correct_answer: str
    explanation: str


class QuizSubmissionResponse(BaseModel):
    id: str
    run_id: str
    score_percent: int
    correct_count: int
    total_questions: int
    feedback: list[QuizQuestionFeedback]
    submitted_at: datetime


class AssignmentSubmissionRequest(BaseModel):
    content: str = Field(min_length=40, max_length=20000)


class LearningProgressRequest(BaseModel):
    lesson_id: str = Field(min_length=1, max_length=160)
    completed: bool


class LearningProgressResponse(BaseModel):
    run_id: str
    lesson_id: str
    completed: bool
    completed_lessons: int
    total_lessons: int


class WorkSubmissionRequest(BaseModel):
    kind: Literal["assignment", "project"]
    response: str = Field(min_length=40, max_length=20000)


class AssignmentSubmissionResponse(BaseModel):
    id: str
    run_id: str
    kind: Literal["assignment", "project"] = "assignment"
    content: str
    status: Literal["submitted", "needs_revision", "accepted"]
    feedback: list[str]
    submitted_at: datetime
