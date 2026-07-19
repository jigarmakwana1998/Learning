"""Pure domain value objects for Learning Coach."""

from .topic_intent import CoverageGaps, CoverageRecord, TopicIntent, compute_coverage_gaps

__all__ = ["CoverageGaps", "CoverageRecord", "TopicIntent", "compute_coverage_gaps"]
