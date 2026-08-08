from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models.database import AgentSessionRecord
from app.schemas.learning import LearningGoal
from app.services.learning_service import LearningService


class FakeDb:
    def __init__(self) -> None:
        self.added = []

    def add(self, record) -> None:
        self.added.append(record)

    async def scalar(self, _statement):
        return 0

    async def flush(self) -> None:
        for index, record in enumerate(self.added):
            if hasattr(record, "id") and record.id is None:
                record.id = f"adaptive-{index}"


class GapGateway:
    def __init__(self, *, readable: bool = True) -> None:
        self.searches: list[str] = []
        self.reads: list[list[str]] = []
        self.readable = readable

    async def browser_search(self, query: str, limit: int = 10) -> dict:
        self.searches.append(query)
        index = len(self.searches) - 1
        return {
            "status": "ok",
            "query": query,
            "results": [{"title": f"Evidence {index}", "url": f"https://evidence-{index}.example.com/guide"}],
        }

    async def browser_read(self, urls: list[str]) -> dict:
        self.reads.append(list(urls))
        if not self.readable:
            return {
                "status": "unavailable",
                "pages": [{"status": "unavailable", "requested_url": url} for url in urls],
            }
        return {
            "status": "ok",
            "pages": [
                {
                    "status": "ok",
                    "requested_url": url,
                    "url": url,
                    "title": "Verified evidence",
                    "content": "bounded evidence " * 80,
                }
                for url in urls
            ],
        }


class GapRuntime:
    def __init__(self, role: str) -> None:
        self.role = role

    async def execute(self, prompt: str):
        payload = json.loads(prompt)
        if self.role == "ResearchQueryPlanner":
            return SimpleNamespace(payload={
                "coverage_requirements": [
                    {"id": "mechanism", "question": "How does the mechanism work?", "priority": "core", "depth": "detailed", "evidence_policy": "single_source_ok"},
                    {"id": "limits", "question": "What are the practical limitations?", "priority": "supporting", "depth": "detailed", "evidence_policy": "single_source_ok"},
                ],
                "queries": [
                    {"query": "authoritative mechanism guide", "purpose": "Cover the mechanism", "coverage_ids": ["mechanism"]},
                    {"query": "authoritative limitations guide", "purpose": "Cover limitations", "coverage_ids": ["limits"]},
                ],
                "seed_candidates": [],
            })
        if self.role == "ResearchSelector":
            candidate = payload["context"]["candidates"][0]
            return SimpleNamespace(payload={"selections": [{"url": candidate["url"], "kind": "documentation"}]})
        if self.role.startswith("ResearchSynthesisPart"):
            page = payload["context"]["pages"][0]
            requirement_id = "mechanism" if "evidence-0" in page["url"] else "limits"
            return SimpleNamespace(payload={
                "topic": payload["learner_goal"]["topic"],
                "sources": [{
                    "title": page["title"], "url": page["url"], "kind": "documentation",
                    "rationale": "Provides specific verified teaching evidence.",
                    "key_points": ["Explains a concrete, browser-verified concept with enough detail for the planned lesson."],
                    "coverage_evidence": [{"requirement_id": requirement_id, "support": "strong"}],
                }],
            })
        sources = payload["context"]["sources"]
        source_urls = {source["url"] for source in sources}
        mechanism_urls = [url for url in source_urls if "evidence-0" in url]
        limit_urls = [url for url in source_urls if "evidence-1" in url]
        return SimpleNamespace(payload={
            "assessments": [
                {"requirement_id": "mechanism", "status": "covered" if mechanism_urls else "missing", "confidence": 0.95, "supported_by": mechanism_urls, "rationale": "Mechanism evidence assessed."},
                {"requirement_id": "limits", "status": "covered" if limit_urls else "missing", "confidence": 0.95 if limit_urls else 0, "supported_by": limit_urls, "rationale": "Limit evidence assessed.", "next_query": "targeted practical limitations evidence" if not limit_urls else None},
            ],
            "sufficient": bool(mechanism_urls and limit_urls),
            "reason": "Coverage assessed.",
        })


class AdaptiveHarness:
    def __init__(self, harness: str, db: FakeDb) -> None:
        self.harness, self.db = harness, db

    async def start_and_run(
        self,
        run_id: str,
        role: str,
        prompt: str,
        *,
        persisted_prompt: str | None = None,
    ):
        execution = await GapRuntime(role).execute(prompt)
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


@pytest.mark.asyncio
async def test_adaptive_loop_searches_again_only_for_a_real_coverage_gap(monkeypatch):
    gateway = GapGateway()
    monkeypatch.setattr("app.services.learning_service.AgentHarness", AdaptiveHarness)
    service = LearningService()
    service.browser_gateway_factory = lambda: gateway

    _, research = await service._browser_research(
        FakeDb(), "run-adaptive", "gemini-cli", LearningGoal(topic="Adaptive systems", weeks=2)
    )

    assert len(gateway.searches) == 2
    assert gateway.searches[0] == "authoritative mechanism guide"
    assert gateway.searches[1] == "targeted practical limitations evidence"
    assert gateway.reads == [
        ["https://evidence-0.example.com/guide"],
        ["https://evidence-1.example.com/guide"],
    ]
    assert research.stop_reason == "coverage_satisfied"
    assert [item.status for item in research.coverage] == ["covered", "covered"]


@pytest.mark.asyncio
async def test_budget_exhaustion_returns_grounded_partial_research(monkeypatch):
    gateway = GapGateway()
    monkeypatch.setattr("app.services.learning_service.AgentHarness", AdaptiveHarness)
    monkeypatch.setattr(
        "app.services.learning_service.get_settings",
        lambda: SimpleNamespace(research_max_pages=1, research_max_searches=1),
    )
    service = LearningService()
    service.browser_gateway_factory = lambda: gateway

    _, research = await service._browser_research(
        FakeDb(), "run-budget", "gemini-cli", LearningGoal(topic="Adaptive systems", weeks=2)
    )

    assert research.stop_reason == "budget_exhausted"
    assert len(research.sources) == 1
    assert [item.status for item in research.coverage] == ["covered", "missing"]
    assert research.warnings


def test_malformed_plan_falls_back_to_one_semantic_discovery_query():
    requirements, queries, seeds = LearningService._validated_query_plan(
        {"coverage_requirements": "broken", "queries": [], "seed_candidates": []},
        LearningGoal(topic="Python functions", weeks=1),
        allow_fallback=True,
    )

    assert len(requirements) == 1
    assert len(queries) == 1
    assert "Python functions" in queries[0]["query"]
    assert seeds == []


def test_corroboration_requires_verified_evidence_from_distinct_hosts():
    requirements = [{
        "id": "claim", "question": "Is the disputed claim supported?", "priority": "core",
        "depth": "detailed", "evidence_policy": "corroborate",
    }]
    one_url = "https://publisher-a.example.com/evidence"
    second_url = "https://publisher-b.example.com/evidence"
    raw = {"assessments": [{
        "requirement_id": "claim", "status": "covered", "confidence": 0.9,
        "supported_by": [one_url, second_url], "rationale": "Two publishers support the claim.",
    }]}

    coverage, _ = LearningService._validated_coverage_assessments(
        raw, requirements, {"claim": {one_url: "strong"}}
    )
    assert coverage[0]["status"] == "partial"

    coverage, _ = LearningService._validated_coverage_assessments(
        raw, requirements, {"claim": {one_url: "strong", second_url: "strong"}}
    )
    assert coverage[0]["status"] == "covered"


@pytest.mark.asyncio
async def test_zero_readable_core_evidence_uses_semantic_failure(monkeypatch):
    gateway = GapGateway(readable=False)
    monkeypatch.setattr("app.services.learning_service.AgentHarness", AdaptiveHarness)
    service = LearningService()
    service.browser_gateway_factory = lambda: gateway

    with pytest.raises(ValueError, match="No verified evidence supports the requested topic"):
        await service._browser_research(
            FakeDb(), "run-empty", "gemini-cli", LearningGoal(topic="Adaptive systems", weeks=2)
        )
