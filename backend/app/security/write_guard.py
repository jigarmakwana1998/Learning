"""Schema-first staging, deterministic validation, and controlled promotion.

Agents submit typed payloads to this module. They do not receive a SQL connection,
table name, query string, or a canonical repository. Implementations of the ports
below must use hard-coded parameterized repository operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class AgentWriteContext(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    run_id: UUID


class ResourceWrite(BaseModel):
    canonical_url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    external_ids: dict[Literal["doi", "isbn", "openalex", "arxiv"], str] = Field(default_factory=dict)
    license: str | None = Field(default=None, max_length=128)


class ConceptWrite(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None


class EvidenceRef(BaseModel):
    resource_version_id: UUID
    section_id: UUID
    char_span_start: int = Field(ge=0)
    char_span_end: int = Field(ge=0)

    def model_post_init(self, __context: Any) -> None:
        if self.char_span_end < self.char_span_start:
            raise ValueError("char_span_end must be greater than or equal to char_span_start")


class ClaimWrite(BaseModel):
    subject_concept_id: UUID
    predicate: Literal["HAS_COMPLEXITY", "PREREQUISITE_OF", "TEACHES", "SUPPORTED_BY", "CONTRADICTS"]
    object_value: str = Field(min_length=1, max_length=500)
    evidence: EvidenceRef
    confidence: float = Field(ge=0, le=1)


AgentPayload = ResourceWrite | ConceptWrite | ClaimWrite


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    errors: tuple[str, ...] = ()


class ReferenceReader(Protocol):
    """Read-only canonical lookup capability made available to the validator."""

    async def concept_exists(self, concept_id: UUID) -> bool: ...

    async def resource_version_exists(self, resource_version_id: UUID) -> bool: ...

    async def section_matches_version(self, section_id: UUID, resource_version_id: UUID) -> bool: ...

    async def duplicate_or_conflicting_claim(self, payload: ClaimWrite) -> bool: ...


class StagingRepository(Protocol):
    """The only write port made available to agent-facing workflows."""

    async def stage(self, context: AgentWriteContext, payload: AgentPayload) -> str: ...

    async def set_validation(self, staged_id: str, result: ValidationResult) -> None: ...

    async def promote(self, staged_id: str) -> str: ...

    async def quarantine_raw(self, context: AgentWriteContext, payload_type: str, raw_payload: dict[str, Any], errors: list[str]) -> str: ...


class DeterministicValidator:
    """Validates payloads without calling an LLM or executing agent-provided code."""

    def __init__(self, references: ReferenceReader):
        self._references = references

    async def validate(self, payload: AgentPayload) -> ValidationResult:
        if isinstance(payload, ResourceWrite):
            return ValidationResult(ValidationStatus.PASSED)
        if isinstance(payload, ConceptWrite):
            return ValidationResult(ValidationStatus.PASSED)

        errors: list[str] = []
        if not await self._references.concept_exists(payload.subject_concept_id):
            errors.append("unknown subject_concept_id")
        if not await self._references.resource_version_exists(payload.evidence.resource_version_id):
            errors.append("unknown evidence resource_version_id")
        if not await self._references.section_matches_version(payload.evidence.section_id, payload.evidence.resource_version_id):
            errors.append("evidence section does not belong to resource version")
        if not errors and await self._references.duplicate_or_conflicting_claim(payload):
            # Contradictions/dedupes require verifier or human approval. The staged
            # record remains intact and auditable, but is never auto-promoted.
            return ValidationResult(ValidationStatus.QUARANTINED, ("duplicate or conflicting claim",))
        return ValidationResult(ValidationStatus.FAILED, tuple(errors)) if errors else ValidationResult(ValidationStatus.PASSED)


class WriteGuard:
    """Single choke point: validate a staged row, then permit promotion once."""

    def __init__(self, staging: StagingRepository, validator: DeterministicValidator):
        self._staging = staging
        self._validator = validator

    async def submit(self, context: AgentWriteContext, payload: AgentPayload) -> str:
        """Persist typed material as pending; agent workflows get no promotion API."""
        return await self._staging.stage(context, payload)

    async def validate_and_promote(self, staged_id: str, payload: AgentPayload) -> str | None:
        result = await self._validator.validate(payload)
        await self._staging.set_validation(staged_id, result)
        if result.status is not ValidationStatus.PASSED:
            return None
        # Only this deterministic service invokes the promoter port after a passed
        # result. Repository implementations must atomically verify the stored
        # status is "passed" before inserting canonical data.
        return await self._staging.promote(staged_id)
