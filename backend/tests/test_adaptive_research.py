from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.mcp.audit import new_session
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


class MultiCandidateGapGateway(GapGateway):
    async def browser_search(self, query: str, limit: int = 10) -> dict:
        self.searches.append(query)
        index = len(self.searches) - 1
        return {
            "status": "ok",
            "query": query,
            "results": [
                {
                    "title": f"Evidence {index}-{candidate_index}",
                    "url": f"https://evidence-{index}.example.com/guide-{candidate_index}",
                }
                for candidate_index in range(3)
            ],
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
            requirement_specs = [
                ("mechanism", "How does the mechanism work?", "core"),
                ("limits", "What are the practical limitations?", "supporting"),
                ("examples", "What worked examples make the behavior observable?", "core"),
                ("integration", "How does the mechanism fit into its wider system?", "core"),
                ("evaluation", "How should a learner evaluate the mechanism?", "supporting"),
            ]
            return SimpleNamespace(payload={
                "coverage_requirements": [
                    {"id": identifier, "question": question, "priority": priority, "depth": "detailed", "evidence_policy": "single_source_ok"}
                    for identifier, question, priority in requirement_specs
                ],
                "queries": [
                    {"query": f"authoritative {identifier} guide", "purpose": f"Cover {identifier}", "coverage_ids": [identifier]}
                    for identifier, _question, _priority in requirement_specs
                ],
                "seed_candidates": [],
            })
        if self.role == "ResearchSelector":
            candidate = payload["context"]["candidates"][0]
            return SimpleNamespace(payload={"selections": [{"url": candidate["url"], "kind": "documentation"}]})
        if self.role.startswith("ResearchSynthesisPart"):
            page = payload["context"]["pages"][0]
            requirement_ids = ["mechanism", "limits", "examples", "integration", "evaluation"]
            source_index = int(page["url"].split("evidence-")[1].split(".")[0])
            requirement_id = requirement_ids[source_index]
            return SimpleNamespace(payload={
                "topic": payload["learner_goal"]["topic"],
                "sources": [{
                    "title": page["title"], "url": page["url"], "kind": "documentation",
                    "rationale": "Provides specific verified teaching evidence.",
                    "key_points": ["Explains a concrete, browser-verified concept with enough detail for the planned lesson."],
                    "coverage_evidence": [{"requirement_id": requirement_id, "support": "strong"}],
                }],
            })
        requirements = payload["context"]["coverage_requirements"]
        sources = payload["context"]["sources"]
        linked_urls = {
            evidence["requirement_id"]: [source["url"]]
            for source in sources
            for evidence in source.get("coverage_evidence", [])
        }
        return SimpleNamespace(payload={
            "assessments": [
                {
                    "requirement_id": requirement["id"],
                    "status": "covered" if requirement["id"] in linked_urls else "missing",
                    "confidence": 0.95 if requirement["id"] in linked_urls else 0,
                    "supported_by": linked_urls.get(requirement["id"], []),
                    "rationale": f"{requirement['id']} evidence assessed.",
                }
                for requirement in requirements
            ],
            "sufficient": len(linked_urls) == len(requirements),
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
        session = new_session(run_id, role, {"prompt": persisted_prompt})
        session.status, session.output_payload = "completed", execution.payload
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
        FakeDb(), "run-adaptive", "deep-agents", LearningGoal(topic="Adaptive systems", weeks=2)
    )

    assert len(gateway.searches) == 5
    assert gateway.searches[0] == "Adaptive systems authoritative mechanism guide"
    assert gateway.searches[1] == "Adaptive systems authoritative limits guide"
    assert gateway.reads == [
        ["https://evidence-0.example.com/guide"],
        ["https://evidence-1.example.com/guide"],
        ["https://evidence-2.example.com/guide"],
        ["https://evidence-3.example.com/guide"],
        ["https://evidence-4.example.com/guide"],
    ]
    assert research.stop_reason == "coverage_satisfied"
    assert [item.status for item in research.coverage] == ["covered"] * 5


@pytest.mark.asyncio
async def test_adaptive_loop_discards_leftover_candidates_after_their_requirement_is_covered(
    monkeypatch,
):
    gateway = MultiCandidateGapGateway()
    monkeypatch.setattr("app.services.learning_service.AgentHarness", AdaptiveHarness)
    service = LearningService()
    service.browser_gateway_factory = lambda: gateway

    _, research = await service._browser_research(
        FakeDb(), "run-candidate-filter", "deep-agents",
        LearningGoal(topic="Adaptive systems", weeks=2),
    )

    read_urls = [url for batch in gateway.reads for url in batch]
    assert len(gateway.searches) == 5
    assert sum("evidence-0.example.com" in url for url in read_urls) == 1
    assert research.stop_reason == "coverage_satisfied"


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
        FakeDb(), "run-budget", "deep-agents", LearningGoal(topic="Adaptive systems", weeks=2)
    )

    assert research.stop_reason == "budget_exhausted"
    assert len(research.sources) == 1
    assert [item.status for item in research.coverage] == [
        "covered", "missing", "missing", "missing", "missing"
    ]
    assert research.warnings


def test_malformed_plan_falls_back_to_curriculum_scale_discovery_queries():
    requirements, queries, seeds = LearningService._validated_query_plan(
        {"coverage_requirements": "broken", "queries": [], "seed_candidates": []},
        LearningGoal(topic="Python functions", weeks=1),
        allow_fallback=True,
    )

    assert len(requirements) == 5
    assert len(queries) == 5
    assert all("Python functions" in item["query"] for item in queries)
    assert {item["id"] for item in requirements} == {
        item["coverage_ids"][0] for item in queries
    }
    assert seeds == []


def test_query_plan_scopes_searches_and_adds_a_discovery_path_for_every_requirement():
    requirement_ids = ["foundations", "mechanism", "examples", "limits", "integration"]
    requirements, queries, _ = LearningService._validated_query_plan(
        {
            "coverage_requirements": [
                {
                    "id": requirement_id,
                    "question": f"What evidence teaches {requirement_id} clearly?",
                    "priority": "core" if index < 3 else "supporting",
                    "depth": "detailed",
                    "evidence_policy": "single_source_ok",
                }
                for index, requirement_id in enumerate(requirement_ids)
            ],
            "queries": [
                {
                    "query": "authoritative mechanism explanation",
                    "purpose": "Find mechanism evidence",
                    "coverage_ids": ["mechanism"],
                }
            ],
            "seed_candidates": [],
        },
        LearningGoal(topic="Python functions", weeks=1),
    )

    assert len(requirements) == 5
    assert all("Python functions" in item["query"] for item in queries)
    assert {
        requirement_id
        for item in queries
        for requirement_id in item["coverage_ids"]
    } == set(requirement_ids)


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
            FakeDb(), "run-empty", "deep-agents", LearningGoal(topic="Adaptive systems", weeks=2)
        )
