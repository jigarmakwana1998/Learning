from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentHarness = Literal["deep-agents"]
SourceKind = Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"]


class LearningGoal(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    hours_per_week: int = Field(default=5, ge=1, le=40)
    weeks: int = Field(default=4, ge=1, le=24)


class AgentOutput(BaseModel):
    """Tool arguments the agent writes. Minimums live here so a violation goes back to the model to fix."""

    # Whitespace-only strings must not satisfy a minimum length.
    model_config = ConfigDict(str_strip_whitespace=True)


class CoverageItem(AgentOutput):
    id: str = Field(min_length=1, description="Short stable id, reused in save_page covers.")
    question: str = Field(min_length=8, description="What the pages must answer for this item.")
    status: Literal["missing", "partial", "covered"] = "missing"


class SavedPage(AgentOutput):
    url: str = Field(min_length=8, description="Exact final URL from a browser_read result.")
    title: str = Field(min_length=2)
    kind: SourceKind
    why: str = Field(min_length=8, description="What this page can teach in this course.")
    key_points: list[Annotated[str, Field(min_length=20)]] = Field(min_length=1)
    covers: list[str] = Field(min_length=1, description="Ids of the coverage items this page supports.")


class ResearchRun(BaseModel):
    id: str
    topic: str
    status: str
    error: str | None = None
    activity: str | None = None
    coverage: list[CoverageItem] = Field(default_factory=list)
    pages: list[SavedPage] = Field(default_factory=list)
