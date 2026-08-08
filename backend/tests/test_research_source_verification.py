from types import SimpleNamespace

import pytest

from app.harness import AgentResult
from app.schemas.learning import LearningRunRequest
from app.services.learning_service import LearningService


SOURCE_KINDS = ("documentation", "paper", "book", "lecture", "slides", "article", "repository")


def source(index: int, url: str | None = None) -> dict:
    return {
        "title": f"Source {index}",
        "url": url or f"https://docs.example.com/source-{index}",
        "kind": SOURCE_KINDS[index % len(SOURCE_KINDS)],
        "rationale": f"Evidence for part {index}",
        "key_points": [
            f"Concrete source-backed mechanism for curriculum part {index}.",
            f"Specific limitation or worked example for curriculum part {index}.",
        ],
    }


def research_output(sources: list[dict], visited_urls=None) -> AgentResult:
    return AgentResult(
        {"topic": "Transformers", "sources": sources},
        visited_urls=frozenset(
            visited_urls if visited_urls is not None else [item["url"] for item in sources]
        ),
    )


def test_accepts_one_read_source_and_normalizes_final_url():
    sources = [source(0)]
    sources[0]["url"] = "HTTPS://DOCS.EXAMPLE.COM/source-0#overview"
    visited = ["https://docs.example.com/source-0"]

    research = LearningService._verified_research(research_output(sources, visited))

    assert len(research.sources) == 1
    assert research.sources[0].url == "https://docs.example.com/source-0"


def test_discards_unread_duplicate_and_search_urls_but_keeps_verified_sources():
    accepted = [source(0)]
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

    assert [item.title for item in research.sources] == ["Source 0"]


def test_keeps_all_verified_sources_within_the_browser_safety_budget():
    sources = [source(index) for index in range(15)]

    research = LearningService._verified_research(research_output(sources))

    assert len(research.sources) == 15


def test_accepts_a_single_authoritative_source_kind():
    sources = [source(index) for index in range(3)]
    for item in sources:
        item["kind"] = "documentation"

    research = LearningService._verified_research(research_output(sources))
    assert len(research.sources) == 3


def test_returns_no_sources_when_no_citation_was_browser_verified():
    research = LearningService._verified_research(research_output([source(0)], []))
    assert research.sources == []


@pytest.mark.asyncio
async def test_create_run_stops_before_planning_when_research_evidence_is_insufficient(monkeypatch):
    harness_calls: list[str] = []

    class FakeDb:
        def __init__(self):
            self.added = []
            self.commits = 0

        async def scalar(self, _statement):
            return SimpleNamespace(value="codex")

        def add(self, record):
            self.added.append(record)

        async def flush(self):
            for index, record in enumerate(self.added):
                if hasattr(record, "id") and record.id is None:
                    record.id = f"record-{index}"

        async def commit(self):
            self.commits += 1

    class FakeHarness:
        def __init__(self, _provider, _db):
            pass

        async def start_and_run(self, _run_id, agent_name, _prompt):
            harness_calls.append(agent_name)
            raise AssertionError("Planner must not run after browser research fails")

    monkeypatch.setattr("app.services.learning_service.AgentHarness", FakeHarness)
    service = LearningService()

    async def fail_research(*_args):
        raise ValueError("No verified evidence supports the requested topic.")

    monkeypatch.setattr(service, "_browser_research", fail_research)
    db = FakeDb()

    with pytest.raises(ValueError, match="No verified evidence"):
        await service.create_run(
            db,
            SimpleNamespace(id="learner"),
            LearningRunRequest(topic="Transformers", weeks=2),
        )

    assert harness_calls == []
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
    sources = [source(0), source(8, url)]
    visited = [item["url"] for item in sources]

    research = LearningService._verified_research(research_output(sources, visited))
    assert [item.url for item in research.sources] == [source(0)["url"]]
