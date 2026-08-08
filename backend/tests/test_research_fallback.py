from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models.database import AgentSessionRecord, McpToolInvocation
from app.schemas.learning import LearningGoal
from app.services.learning_service import LearningService


KINDS = ("documentation", "paper", "book", "lecture", "slides", "article", "repository")


class FakeDb:
    def __init__(self) -> None:
        self.added = []
        self._next_id = 0

    def add(self, record) -> None:
        self.added.append(record)

    async def flush(self) -> None:
        for record in self.added:
            if hasattr(record, "id") and record.id is None:
                self._next_id += 1
                record.id = f"research-{self._next_id}"

    async def scalar(self, _statement):
        return 0


class FakeGateway:
    def __init__(self) -> None:
        self.searches: list[tuple[str, int]] = []
        self.read_batches: list[list[str]] = []

    async def browser_search(self, query: str, limit: int = 10) -> dict:
        self.searches.append((query, limit))
        start = 0 if len(self.searches) == 1 else 6
        return {
            "status": "ok",
            "query": query,
            "results": [
                {"title": f"Candidate {index}", "url": f"https://sources.example.com/source-{index}"}
                for index in range(start, start + 6)
            ],
        }

    async def browser_read(self, urls: list[str]) -> dict:
        self.read_batches.append(list(urls))
        pages = []
        for url in urls:
            index = int(url.rsplit("-", 1)[1])
            if index in {1, 3}:
                pages.append({"status": "unavailable", "requested_url": url})
            else:
                pages.append(
                    {
                        "status": "ok",
                        "url": url,
                        "title": f"Read source {index}",
                        "content": f"UNTRUSTED_PAGE_BODY_{index} " + ("bounded evidence " * 40),
                    }
                )
        return {"status": "ok", "pages": pages}


class FakePlainRuntime:
    def __init__(self, role: str, calls: list[str]) -> None:
        self.role = role
        self.calls = calls

    async def execute(self, prompt: str):
        self.calls.append(self.role)
        payload = json.loads(prompt)
        if self.role == "ResearchQueryPlanner":
            return SimpleNamespace(
                payload={
                    "queries": [
                        {"query": f"Lead{index} transformer evidence angle", "purpose": f"Coverage purpose {index}"}
                        for index in range(8)
                    ],
                    "replacement_queries": [
                        {"query": f"Replacement{index} transformer evidence", "purpose": f"Replacement purpose {index}"}
                        for index in range(2)
                    ],
                    "seed_candidates": [
                        {
                            "title": f"Seed {index}",
                            "url": f"https://seeds.example.com/source-{index}",
                            "purpose": f"Canonical evidence seed {index}",
                        }
                        for index in range(8)
                    ],
                }
            )
        if self.role == "ResearchSelector":
            candidates = payload["context"]["candidates"]
            return SimpleNamespace(
                payload={
                    "selections": [
                        {"url": item["url"], "kind": KINDS[index % len(KINDS)]}
                        for index, item in enumerate(candidates[:12])
                    ]
                }
            )
        pages = payload["context"]["pages"]
        return SimpleNamespace(
            payload={
                "topic": payload["learner_goal"]["topic"],
                "sources": [
                    {
                        "title": page["title"],
                        "url": page["url"],
                        "kind": KINDS[index % len(KINDS)],
                        "rationale": f"Grounds the course section using readable evidence {index}.",
                        "key_points": [
                            f"Explains a concrete mechanism from readable source {index}.",
                            f"Provides a limitation or worked example from source {index}.",
                        ],
                    }
                    for index, page in enumerate(pages)
                ],
            }
        )


@pytest.mark.asyncio
async def test_browser_research_is_bounded_grounded_and_body_free_in_audit(monkeypatch):
    gateway = FakeGateway()
    calls: list[str] = []

    class FakeHarness:
        def __init__(self, harness: str, db: FakeDb):
            self.harness, self.db = harness, db

        async def start_and_run(self, run_id: str, role: str, prompt: str):
            execution = await FakePlainRuntime(role, calls).execute(prompt)
            session = AgentSessionRecord(
                agent_run_id=run_id,
                agent_name=role,
                harness=self.harness,
                status="completed",
                output_payload=execution.payload,
            )
            self.db.add(session)
            await self.db.flush()
            return session, execution.payload

    monkeypatch.setattr(
        "app.services.learning_service.AgentHarness",
        FakeHarness,
    )
    service = LearningService()
    service.browser_gateway_factory = lambda: gateway
    db = FakeDb()

    session, research = await service._browser_research(
        db,
        "run-1",
        "gemini-cli",
        LearningGoal(topic="Transformers", weeks=2),
    )

    assert session.agent_name == "ResearchSynthesisPart1"
    assert calls == [
        "ResearchQueryPlanner", "ResearchSelector",
        "ResearchSynthesisPart1", "ResearchSynthesisPart2",
    ]
    assert len(gateway.searches) == 8
    assert len(gateway.read_batches) == 3
    assert all(1 <= len(batch) <= 4 for batch in gateway.read_batches)
    assert sum(map(len, gateway.read_batches)) == 12
    assert len(research.sources) == 8
    assert {source.kind for source in research.sources} >= {
        "documentation", "paper", "book", "lecture", "article", "repository"
    }

    audits = [item for item in db.added if isinstance(item, McpToolInvocation)]
    assert [item.tool_name for item in audits] == [
        *(["browser_search"] * 8),
        "browser_read", "browser_read", "browser_read"
    ]
    assert all("content" not in json.dumps(item.metadata_json).casefold() for item in audits)
    assert all("UNTRUSTED_PAGE_BODY" not in json.dumps(item.metadata_json) for item in audits)
    browser_session = next(
        item for item in db.added
        if isinstance(item, AgentSessionRecord) and item.agent_name == "BrowserResearch"
    )
    assert browser_session.status == "completed"
    assert browser_session.output_payload["read_count"] == 8
    persisted_sessions = [item for item in db.added if isinstance(item, AgentSessionRecord)]
    assert all(
        "UNTRUSTED_PAGE_BODY" not in json.dumps(
            {"input": item.input_payload, "output": item.output_payload}
        )
        for item in persisted_sessions
    )
