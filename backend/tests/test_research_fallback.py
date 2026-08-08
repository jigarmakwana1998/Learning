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
                    "coverage_requirements": [{
                        "id": "core",
                        "question": "How do transformers work in practice?",
                        "priority": "core",
                        "depth": "detailed",
                        "evidence_policy": "single_source_ok",
                    }],
                    "queries": [
                        {"query": "transformer architecture authoritative guide", "purpose": "Cover the core mechanism", "coverage_ids": ["core"]}
                    ],
                    "seed_candidates": [
                        {
                            "title": "Canonical transformer guide",
                            "url": "https://seeds.example.com/source-0",
                            "purpose": "Canonical evidence for the core mechanism",
                            "coverage_ids": ["core"],
                            "kind": "documentation",
                        }
                    ],
                }
            )
        if self.role == "ResearchSelector":
            candidates = payload["context"]["candidates"]
            return SimpleNamespace(
                payload={
                    "selections": [{"url": candidates[0]["url"], "kind": "documentation", "coverage_ids": ["core"]}]
                }
            )
        if self.role.startswith("ResearchCoverageRound"):
            sources = payload["context"]["sources"]
            return SimpleNamespace(payload={
                "assessments": [{
                    "requirement_id": "core",
                    "status": "covered",
                    "confidence": 0.95,
                    "supported_by": [sources[0]["url"]],
                    "rationale": "The canonical guide covers the required mechanism.",
                }],
                "sufficient": True,
                "reason": "All requirements are covered.",
            })
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
                        ],
                        "coverage_evidence": [{"requirement_id": "core", "support": "strong"}],
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

        async def start_and_run(
            self,
            run_id: str,
            role: str,
            prompt: str,
            *,
            persisted_prompt: str | None = None,
        ):
            execution = await FakePlainRuntime(role, calls).execute(prompt)
            session = AgentSessionRecord(
                agent_run_id=run_id,
                agent_name=role,
                harness=self.harness,
                status="completed",
                    output_payload=execution.payload,
                    input_payload={"prompt": persisted_prompt},
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
        "ResearchSynthesisPart1", "ResearchCoverageRound1",
    ]
    assert gateway.searches == []
    assert gateway.read_batches == [["https://seeds.example.com/source-0"]]
    assert len(research.sources) == 1
    assert research.stop_reason == "coverage_satisfied"
    assert research.coverage[0].status == "covered"

    audits = [item for item in db.added if isinstance(item, McpToolInvocation)]
    assert [item.tool_name for item in audits] == [
        "browser_read"
    ]
    assert all("content" not in json.dumps(item.metadata_json).casefold() for item in audits)
    assert all("UNTRUSTED_PAGE_BODY" not in json.dumps(item.metadata_json) for item in audits)
    browser_session = next(
        item for item in db.added
        if isinstance(item, AgentSessionRecord) and item.agent_name == "BrowserResearch"
    )
    assert browser_session.status == "completed"
    assert browser_session.output_payload["read_count"] == 1
    persisted_sessions = [item for item in db.added if isinstance(item, AgentSessionRecord)]
    assert all(
        "UNTRUSTED_PAGE_BODY" not in json.dumps(
            {"input": item.input_payload, "output": item.output_payload}
        )
        for item in persisted_sessions
    )
