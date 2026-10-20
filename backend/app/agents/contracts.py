from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.learning import Assessment, CurriculumModule, LessonParagraph


class PlannerOutput(BaseModel):
    curriculum: list[CurriculumModule]
    assessment: Assessment


class LessonExpansion(BaseModel):
    id: str
    paragraphs: list[LessonParagraph]


class LessonWriterOutput(BaseModel):
    lesson: LessonExpansion


class CoverageRequirementOutput(BaseModel):
    id: str
    question: str
    priority: Literal["core", "supporting"]
    depth: Literal["overview", "detailed"]
    evidence_policy: Literal["single_source_ok", "corroborate"]


class ResearchQueryOutput(BaseModel):
    query: str
    purpose: str
    coverage_ids: list[str]


class SeedCandidateOutput(BaseModel):
    title: str
    url: str
    purpose: str
    coverage_ids: list[str]
    kind: Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"] | None = None


class ResearchPlanOutput(BaseModel):
    coverage_requirements: list[CoverageRequirementOutput]
    queries: list[ResearchQueryOutput]
    seed_candidates: list[SeedCandidateOutput] = Field(default_factory=list)


class ResearchSelectionOutput(BaseModel):
    url: str
    kind: Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"]
    coverage_ids: list[str]
    reason: str
    expected_information_gain: float = Field(ge=0, le=1)


class ResearchSelectionsOutput(BaseModel):
    selections: list[ResearchSelectionOutput]


class CoverageEvidenceOutput(BaseModel):
    requirement_id: str
    support: Literal["strong", "partial"]


class SynthesizedSourceOutput(BaseModel):
    title: str
    url: str
    kind: Literal["documentation", "paper", "book", "lecture", "slides", "article", "repository"]
    rationale: str
    key_points: list[str]
    coverage_evidence: list[CoverageEvidenceOutput]


class ResearchSynthesisOutput(BaseModel):
    topic: str
    sources: list[SynthesizedSourceOutput]


class CoverageAssessmentOutput(BaseModel):
    requirement_id: str
    status: Literal["covered", "partial", "missing"]
    confidence: float = Field(ge=0, le=1)
    supported_by: list[str]
    rationale: str
    next_query: str | None = None


class ResearchCoverageOutput(BaseModel):
    assessments: list[CoverageAssessmentOutput]
    sufficient: bool
    reason: str


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
