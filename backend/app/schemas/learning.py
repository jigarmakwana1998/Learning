from typing import Literal

from pydantic import BaseModel, Field

AgentProvider = Literal["mock", "codex", "gemini-cli", "antigravity-cli"]


class LearningGoal(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    hours_per_week: int = Field(default=5, ge=1, le=40)
    weeks: int = Field(default=4, ge=1, le=24)


class LearningRunRequest(LearningGoal):
    provider: AgentProvider | None = None


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


class Assessment(BaseModel):
    quiz: list[str]
    assignment: str
    project: str


class LearningRun(BaseModel):
    id: str
    provider: AgentProvider
    research: ResearchBrief
    curriculum: list[CurriculumModule]
    assessment: Assessment
    sessions: dict[str, str]


class EvaluationRequest(BaseModel):
    score_percent: int = Field(ge=0, le=100)
    confidence: Literal["low", "medium", "high"]


class EvaluationResponse(BaseModel):
    run_id: str
    recommendation: str
