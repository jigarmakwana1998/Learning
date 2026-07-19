from uuid import uuid4

import pytest

from app.security.write_guard import (
    AgentWriteContext,
    ClaimWrite,
    DeterministicValidator,
    EvidenceRef,
    ResourceWrite,
    ValidationStatus,
    WriteGuard,
)


class References:
    def __init__(self, valid: bool):
        self.valid = valid

    async def concept_exists(self, _): return self.valid
    async def resource_version_exists(self, _): return self.valid
    async def section_matches_version(self, _, __): return self.valid
    async def duplicate_or_conflicting_claim(self, _): return False


class Staging:
    def __init__(self):
        self.statuses = []
        self.promoted = []

    async def stage(self, _, __): return "staged-1"
    async def set_validation(self, staged_id, result): self.statuses.append((staged_id, result))
    async def promote(self, staged_id):
        assert self.statuses[-1][1].status is ValidationStatus.PASSED
        self.promoted.append(staged_id)
        return "canonical-1"
    async def quarantine_raw(self, *_): return "quarantined-1"


def claim() -> ClaimWrite:
    version_id, section_id = uuid4(), uuid4()
    return ClaimWrite(
        subject_concept_id=uuid4(), predicate="TEACHES", object_value="functions", confidence=0.9,
        evidence=EvidenceRef(resource_version_id=version_id, section_id=section_id, char_span_start=1, char_span_end=3),
    )


@pytest.mark.asyncio
async def test_failed_claim_is_retained_but_never_promoted():
    staging = Staging()
    guard = WriteGuard(staging, DeterministicValidator(References(valid=False)))

    assert await guard.validate_and_promote("staged-1", claim()) is None
    assert staging.statuses[-1][1].status is ValidationStatus.FAILED
    assert staging.promoted == []


@pytest.mark.asyncio
async def test_only_validated_payload_is_promoted():
    staging = Staging()
    guard = WriteGuard(staging, DeterministicValidator(References(valid=True)))

    assert await guard.validate_and_promote("staged-1", claim()) == "canonical-1"
    assert staging.promoted == ["staged-1"]


@pytest.mark.asyncio
async def test_agent_port_can_only_stage_typed_payload():
    staging = Staging()
    guard = WriteGuard(staging, DeterministicValidator(References(valid=True)))
    context = AgentWriteContext(agent_id="scout", prompt_version="v1", model_id="test", run_id=uuid4())

    assert await guard.submit(context, ResourceWrite(canonical_url="https://example.com/resource", title="Resource")) == "staged-1"
