from datetime import datetime, timedelta, timezone

from app.domain.topic_intent import CoverageGaps, CoverageRecord, TopicIntent, compute_coverage_gaps


def test_equivalent_topic_intents_have_one_deterministic_fingerprint():
    first = TopicIntent("  Python\u00a0Basics ", ("Functions", " variables "), ("Write Code",), "Beginner", ("paper", "documentation"), 30)
    second = TopicIntent("python basics", ("variables", "FUNCTIONS"), ("write code",), "beginner", ("DOCUMENTATION", "Paper"), 30)

    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


def test_coverage_gaps_distinguish_reusable_partial_missing_and_stale():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    intent = TopicIntent("Python", ("syntax", "functions", "typing", "legacy"), source_types=("documentation",))
    records = [
        CoverageRecord("a", ("syntax",), (), ("documentation",), now + timedelta(days=1), 1.0),
        CoverageRecord("b", ("functions",), (), ("article",), now + timedelta(days=1), 1.0),
        CoverageRecord("c", ("legacy",), (), ("documentation",), now - timedelta(seconds=1), 1.0),
    ]

    assert compute_coverage_gaps(intent, records, observed_at=now) == CoverageGaps(
        reusable=("syntax",), partially_covered=("functions",), missing=("typing",), stale=("legacy",)
    )
