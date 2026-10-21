"""Structured output schemas for every agent.

Minimums for required fields live here, not in service code: the model receives
this schema with its task, and a violation is returned to it as a validation
error to fix.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.learning import LessonParagraph

SourceKind = Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"]
Text = Annotated[str, Field(min_length=1)]


class AgentOutput(BaseModel):
    # Whitespace-only strings must not satisfy a minimum length.
    model_config = ConfigDict(str_strip_whitespace=True)


class PlannedSection(AgentOutput):
    title: str = Field(min_length=3)
    objective: str = Field(min_length=12)
    coverage_ids: list[Text] = Field(min_length=1)
    key_points: list[Text] = Field(min_length=1)
    estimated_minutes: int = Field(ge=1)


class PlannedChapter(AgentOutput):
    title: str = Field(min_length=3)
    summary: str = Field(min_length=20)
    sections: list[PlannedSection] = Field(min_length=1)


class PlannerOutput(AgentOutput):
    """Course structure only: chapters and their sections. Lesson text, sources, and
    assessments are produced by later agents."""

    chapters: list[PlannedChapter] = Field(min_length=1)


class LessonExpansion(AgentOutput):
    id: Text
    paragraphs: list[LessonParagraph] = Field(min_length=1)


class LessonWriterOutput(AgentOutput):
    lesson: LessonExpansion


class CoverageRequirementOutput(AgentOutput):
    id: Text
    question: str = Field(min_length=8)
    priority: Literal["core", "supporting"]
    depth: Literal["overview", "detailed"]
    evidence_policy: Literal["single_source_ok", "corroborate"]


class ResearchQueryOutput(AgentOutput):
    query: str = Field(min_length=3)
    purpose: Text
    coverage_ids: list[Text] = Field(min_length=1)


class SeedCandidateOutput(AgentOutput):
    title: Text
    url: Text
    purpose: Text
    coverage_ids: list[Text] = Field(min_length=1)
    kind: SourceKind | None = None


class ResearchPlanOutput(AgentOutput):
    coverage_requirements: list[CoverageRequirementOutput] = Field(min_length=1)
    queries: list[ResearchQueryOutput] = Field(min_length=1)
    seed_candidates: list[SeedCandidateOutput] = Field(default_factory=list)


class ResearchSelectionOutput(AgentOutput):
    url: Text
    kind: SourceKind
    coverage_ids: list[str]
    reason: Text


class ResearchSelectionsOutput(AgentOutput):
    selections: list[ResearchSelectionOutput]


class CoverageEvidenceOutput(AgentOutput):
    requirement_id: Text
    support: Literal["strong", "partial"]


class SynthesizedSourceOutput(AgentOutput):
    title: str = Field(min_length=2)
    url: Text
    kind: SourceKind
    rationale: str = Field(min_length=8)
    key_points: list[Annotated[str, Field(min_length=20)]] = Field(min_length=1)
    coverage_evidence: list[CoverageEvidenceOutput]


class ResearchSynthesisOutput(AgentOutput):
    topic: Text
    sources: list[SynthesizedSourceOutput]


class CoverageAssessmentOutput(AgentOutput):
    requirement_id: Text
    status: Literal["covered", "partial", "missing"]
    confidence: float = Field(ge=0, le=1)
    supported_by: list[str]
    rationale: Text
    next_query: str | None = None


class ResearchCoverageOutput(AgentOutput):
    assessments: list[CoverageAssessmentOutput]


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "Planner": PlannerOutput,
    "LessonWriter": LessonWriterOutput,
    "ResearchQueryPlanner": ResearchPlanOutput,
    "ResearchSelector": ResearchSelectionsOutput,
}


def output_schema_for(agent_name: str) -> type[BaseModel] | None:
    if agent_name.startswith("ResearchSynthesis"):
        return ResearchSynthesisOutput
    if agent_name.startswith("ResearchCoverage"):
        return ResearchCoverageOutput
    return OUTPUT_SCHEMAS.get(agent_name)
