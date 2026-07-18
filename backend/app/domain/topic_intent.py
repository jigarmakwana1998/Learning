"""Deterministic topic-intent identity and coverage-gap calculation.

This module deliberately has no framework or database imports.  The fingerprint is
an idempotency key: equivalent user intents produce the same key regardless of
input ordering or whitespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import unicodedata


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _normalized_set(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({_normalize(value) for value in values if _normalize(value)}))


@dataclass(frozen=True, slots=True)
class TopicIntent:
    """The stable, queryable representation of a research request."""

    topic: str
    concepts: tuple[str, ...] = ()
    learning_objectives: tuple[str, ...] = ()
    expertise_level: str = "beginner"
    source_types: tuple[str, ...] = ()
    time_window_days: int | None = None

    def canonical_payload(self) -> dict[str, object]:
        if self.time_window_days is not None and self.time_window_days < 1:
            raise ValueError("time_window_days must be positive when supplied")
        topic = _normalize(self.topic)
        if not topic:
            raise ValueError("topic must not be empty")
        return {
            "v": 1,
            "topic": topic,
            "concepts": _normalized_set(self.concepts),
            "learning_objectives": _normalized_set(self.learning_objectives),
            "expertise_level": _normalize(self.expertise_level),
            "source_types": _normalized_set(self.source_types),
            "time_window_days": self.time_window_days,
        }

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    intent_fingerprint: str
    concepts: tuple[str, ...]
    learning_objectives: tuple[str, ...]
    source_types: tuple[str, ...]
    fresh_until: datetime | None
    coverage_score: float


@dataclass(frozen=True, slots=True)
class CoverageGaps:
    reusable: tuple[str, ...]
    partially_covered: tuple[str, ...]
    missing: tuple[str, ...]
    stale: tuple[str, ...]


def compute_coverage_gaps(
    intent: TopicIntent,
    records: tuple[CoverageRecord, ...] | list[CoverageRecord],
    *,
    observed_at: datetime | None = None,
) -> CoverageGaps:
    """Classify requested concepts for planner dispatch without making DB calls."""
    now = observed_at or datetime.now(timezone.utc)
    requested = set(_normalized_set(intent.concepts))
    reusable: set[str] = set()
    partial: set[str] = set()
    stale: set[str] = set()
    wanted_sources = set(_normalized_set(intent.source_types))

    for record in records:
        covered = set(_normalized_set(record.concepts)) & requested
        if not covered:
            continue
        expired = record.fresh_until is not None and record.fresh_until <= now
        source_match = not wanted_sources or wanted_sources.issubset(set(_normalized_set(record.source_types)))
        if expired:
            stale.update(covered)
        elif record.coverage_score >= 0.95 and source_match:
            reusable.update(covered)
        else:
            partial.update(covered)

    # Fresh complete coverage wins over partial coverage, but stale data is never
    # reusable. A planner can refresh stale concepts while preserving audit history.
    reusable.difference_update(stale)
    partial.difference_update(reusable | stale)
    missing = requested - reusable - partial - stale
    return CoverageGaps(
        reusable=tuple(sorted(reusable)),
        partially_covered=tuple(sorted(partial)),
        missing=tuple(sorted(missing)),
        stale=tuple(sorted(stale)),
    )
