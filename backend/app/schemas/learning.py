from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentHarness = Literal["deep-agents"]


class LearningGoal(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    hours_per_week: int = Field(default=5, ge=1, le=40)
    weeks: int = Field(default=4, ge=1, le=24)


class AgentOutput(BaseModel):
    """Agent-written metadata, without content length or completeness requirements."""
    model_config = ConfigDict(str_strip_whitespace=True)


class CoverageItem(AgentOutput):
    id: str = Field(description="Short stable id, reused in save_page covers.")
    question: str = Field(description="What the pages should answer for this item.")
    status: Literal["missing", "partial", "covered"] = "missing"


class SavedPage(AgentOutput):
    url: str = Field(description="URL of the source page.")
    title: str = ""
    kind: str = "article"
    why: str = ""
    key_points: list[str] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list, description="Coverage ids this page supports, when available.")


class ResearchRun(BaseModel):
    id: str
    topic: str
    status: str
    error: str | None = None
    activity: str | None = None
    coverage: list[CoverageItem] = Field(default_factory=list)
    pages: list[SavedPage] = Field(default_factory=list)
