import pytest

from app.core.security import encrypt


@pytest.mark.benchmark(group="transcript")
def test_transcript_encryption_benchmark(benchmark):
    value = benchmark(encrypt, "A normal transcript entry about learning Python.")
    assert value
