from typing import Literal

from pydantic import BaseModel, Field

AgentHarness = Literal["deep-agents"]


class LearningGoal(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    hours_per_week: int = Field(default=5, ge=1, le=40)
    weeks: int = Field(default=4, ge=1, le=24)


class LearningRunRequest(LearningGoal):
    pass


class Source(BaseModel):
    title: str = Field(min_length=2)
    url: str
    kind: Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"]
    rationale: str = Field(min_length=8)
    key_points: list[str] = Field(default_factory=list)


class SourceVisit(BaseModel):
    url: str
    title: str | None = None
    status: Literal["discovered", "read", "unavailable"]
    selected: bool = False


class ResearchCoverage(BaseModel):
    requirement_id: str
    question: str
    priority: Literal["core", "supporting"]
    depth: Literal["overview", "detailed"]
    evidence_policy: Literal["single_source_ok", "corroborate"]
    status: Literal["covered", "partial", "missing"]
    confidence: float = Field(ge=0, le=1)
    supported_by: list[str] = Field(default_factory=list)
    rationale: str = ""


class ResearchStats(BaseModel):
    rounds: int = 0
    searches: int = 0
    pages_attempted: int = 0
    pages_read: int = 0
    sources_selected: int = 0


class ResearchBrief(BaseModel):
    topic: str
    sources: list[Source]
    visited_sources: list[SourceVisit] = Field(default_factory=list)
    coverage: list[ResearchCoverage] = Field(default_factory=list)
    stop_reason: Literal["coverage_satisfied", "budget_exhausted", "no_new_evidence"] | None = None
    warnings: list[str] = Field(default_factory=list)
    research_stats: ResearchStats = Field(default_factory=ResearchStats)


class LearningRun(BaseModel):
    id: str
    harness: AgentHarness
    research: ResearchBrief
    sessions: dict[str, str]
