from types import SimpleNamespace

import pytest

from app.harness import AgentResult
from app.schemas.learning import LearningRunRequest
from app.services.learning_service import LearningService


SOURCE_KINDS = ("documentation", "paper", "book", "lecture", "article", "repository")


def source(index: int, url: str | None = None) -> dict:
    return {
        "title": f"Source {index}",
        "url": url or f"https://docs.example.com/source-{index}",
        "kind": SOURCE_KINDS[index % len(SOURCE_KINDS)],
        "rationale": f"Evidence for part {index}",
    }


def research_output(sources: list[dict], visited_urls=None) -> AgentResult:
    return AgentResult(
        {"topic": "Transformers", "sources": sources},
        visited_urls=frozenset(
            visited_urls if visited_urls is not None else [item["url"] for item in sources]
        ),
    )


def test_accepts_eight_unique_read_sources_and_normalizes_final_urls():
    sources = [source(index) for index in range(8)]
    sources[0]["url"] = "HTTPS://DOCS.EXAMPLE.COM/source-0#overview"
    visited = ["https://docs.example.com/source-0", *(item["url"] for item in sources[1:])]

    research = LearningService._verified_research(research_output(sources, visited))

    assert len(research.sources) == 8
    assert research.sources[0].url == "https://docs.example.com/source-0"


def test_discards_unread_duplicate_and_search_urls_but_keeps_verified_sources():
    accepted = [source(index) for index in range(8)]
    rejected = [
        source(20, "https://unread.example.com/article"),
        source(21, accepted[0]["url"] + "#duplicate"),
        source(22, "https://www.google.com/search?q=transformers"),
    ]
    visited = [
        *(item["url"] for item in accepted),
        rejected[2]["url"],
    ]

    research = LearningService._verified_research(research_output([*accepted, *rejected], visited))

    assert [item.title for item in research.sources] == [f"Source {index}" for index in range(8)]


def test_caps_verified_sources_at_twelve():
    sources = [source(index) for index in range(15)]

    research = LearningService._verified_research(research_output(sources))

    assert len(research.sources) == 12


def test_rejects_a_brief_without_the_required_source_mix():
    sources = [source(index) for index in range(8)]
    for item in sources:
        item["kind"] = "documentation"

    with pytest.raises(ValueError, match="must cover documentation, paper, book, lecture, and article"):
        LearningService._verified_research(research_output(sources))


@pytest.mark.parametrize(
    "sources,visited",
    [
        ([source(index) for index in range(8)], []),
        ([source(index) for index in range(7)], None),
        (
            [source(index, "https://docs.example.com/same") for index in range(8)],
            ["https://docs.example.com/same"],
        ),
    ],
)
def test_fails_clearly_when_fewer_than_eight_unique_sources_were_read(sources, visited):
    with pytest.raises(ValueError, match="at least 8 unique browser-verified sources"):
        LearningService._verified_research(research_output(sources, visited))


@pytest.mark.asyncio
async def test_create_run_stops_before_planning_when_research_evidence_is_insufficient(monkeypatch):
    invalid_research = research_output([source(index) for index in range(8)], [])

    class FakeDb:
        def __init__(self):
            self.added = []
            self.commits = 0

        async def scalar(self, _statement):
            return SimpleNamespace(value="gemini-cli")

        def add(self, record):
            self.added.append(record)

        async def flush(self):
            for index, record in enumerate(self.added):
                if hasattr(record, "id") and record.id is None:
                    record.id = f"record-{index}"

        async def commit(self):
            self.commits += 1

    class FakeHarness:
        calls = []

        def __init__(self, _provider, _db):
            pass

        async def start_and_run(self, _run_id, agent_name, _prompt):
            self.calls.append(agent_name)
            return SimpleNamespace(id="research-session"), invalid_research

    monkeypatch.setattr("app.services.learning_service.AgentHarness", FakeHarness)
    db = FakeDb()

    with pytest.raises(ValueError, match="at least 8 unique browser-verified sources"):
        await LearningService().create_run(
            db,
            SimpleNamespace(id="learner"),
            LearningRunRequest(topic="Transformers", weeks=2),
        )

    assert FakeHarness.calls == ["Researcher"]
    assert db.commits == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.com/source",
        "https://user:password@docs.example.com/source",
        "https://docs.example.com:8443/source",
        "https://127.0.0.1/source",
        "https://metadata.google.internal/source",
        "not a URL",
    ],
)
def test_rejects_malformed_or_non_https_citations(url):
    sources = [source(index) for index in range(7)] + [source(8, url)]
    visited = [item["url"] for item in sources]

    with pytest.raises(ValueError, match="received 7"):
        LearningService._verified_research(research_output(sources, visited))
