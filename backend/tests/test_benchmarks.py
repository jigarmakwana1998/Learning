import pytest

from app.core.security import encrypt
from app.schemas.learning import LearningGoal
from app.services.learning_service import LearningService


@pytest.mark.benchmark(group="transcript")
def test_transcript_encryption_benchmark(benchmark):
    value = benchmark(encrypt, "A normal transcript entry about learning Python.")
    assert value


@pytest.mark.benchmark(group="mock_pipeline")
def test_mock_pipeline_benchmark(benchmark):
    run = benchmark(LearningService()._mock_run, LearningGoal(topic="Python", weeks=8, hours_per_week=5), "mock", {"Researcher": "r", "Planner": "p", "Examiner": "e"})
    assert len(run.curriculum) == 8
