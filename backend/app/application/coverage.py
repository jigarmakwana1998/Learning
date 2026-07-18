"""Coverage-ledger query port and deterministic planner helper."""

from __future__ import annotations

from typing import Protocol

from app.domain.topic_intent import CoverageGaps, CoverageRecord, TopicIntent, compute_coverage_gaps


class CoverageLedgerReader(Protocol):
    async def find_candidates(self, intent: TopicIntent) -> list[CoverageRecord]: ...


async def gaps_for_intent(reader: CoverageLedgerReader, intent: TopicIntent) -> CoverageGaps:
    """Return reusable/partial/missing/stale sets for a topic-planner workflow."""
    return compute_coverage_gaps(intent, await reader.find_candidates(intent))
