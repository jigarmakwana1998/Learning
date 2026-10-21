import ipaddress
import logging
import re
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    ResearchCoverageEvaluatorAgent, ResearchQueryPlannerAgent, ResearchSelectorAgent,
    ResearchSynthesisAgent,
)
from app.agents.contracts import ResearchPlanOutput
from browser_mcp.config import browser_settings
from browser_mcp.gateway import BrowserGateway
from learning_db.session import SessionLocal
from app.core.security import encrypt
from app.harness import AgentHarness
from app.tracing import record_tool_invocation, record_trace_event
from learning_db.models import AgentRun, AgentSessionRecord, LearningRequest, TranscriptEntryRecord, User
from app.schemas.learning import LearningGoal, LearningRun, LearningRunRequest, ResearchBrief, Source, SourceVisit

logger = logging.getLogger(__name__)


class LearningService:
    browser_gateway_factory = BrowserGateway

    async def create_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> LearningRun:
        run = await self.start_run(db, user, request)
        return await self.execute_run(db, run, LearningGoal.model_validate(request))

    async def start_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> AgentRun:
        """Persist a running run so callers can return its id before generation finishes."""
        goal = LearningGoal.model_validate(request)
        learning_request = LearningRequest(user_id=user.id, topic=goal.topic, level=goal.level, hours_per_week=goal.hours_per_week, weeks=goal.weeks)
        db.add(learning_request)
        await db.flush()
        run = AgentRun(learning_request_id=learning_request.id, harness="deep-agents")
        db.add(run)
        await db.commit()
        return run

    async def execute_in_background(self, run_id: str, request: LearningRunRequest) -> None:
        # ponytail: in-process task, lost on restart (startup marks it failed);
        # move to a job queue if runs must survive restarts or scale out.
        async with SessionLocal() as db:
            run = await db.get(AgentRun, run_id)
            try:
                await self.execute_run(db, run, LearningGoal.model_validate(request))
            except Exception:
                logger.exception("learning run %s failed", run_id)

    async def execute_run(self, db: AsyncSession, run: AgentRun, goal: LearningGoal) -> LearningRun:
        try:
            research_session, research = await self._browser_research(db, run.id, run.harness, goal)
            self._require_covered_research(research)
            result = LearningRun(
                id=run.id, harness=run.harness, research=research,
                sessions={"Researcher": research_session.id},
            )
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return result
        except Exception as error:
            detail = str(error) if isinstance(error, RuntimeError | ValueError) else "Research failed"
            run.status, run.result, run.completed_at = "failed", {"error": detail}, datetime.now(timezone.utc)
            await db.commit()
            raise

    async def _browser_research(
        self,
        db: AsyncSession,
        run_id: str,
        harness: str,
        goal: LearningGoal,
    ) -> tuple[AgentSessionRecord, ResearchBrief]:
        """Browse until semantic coverage is complete or a safety boundary is reached."""
        gateway = self.browser_gateway_factory()
        settings = browser_settings()
        audit_session = AgentSessionRecord(
            agent_run_id=run_id,
            agent_name="BrowserResearch",
            harness=harness,
            input_payload={"agent": "Researcher", "pipeline": "browser-research"},
        )
        db.add(audit_session)
        await db.flush()
        await record_trace_event(
            db,
            run_id=run_id,
            session_id=audit_session.id,
            event_type="lifecycle",
            name="browser.pipeline.started",
            input_payload={"goal": goal.model_dump(mode="json")},
            metadata={"harness": harness, "pipeline": "browser-research"},
        )
        started = perf_counter()
        try:
            query_planner = ResearchQueryPlannerAgent()
            query_session, query_output = await self._plain_research_call(
                db,
                run_id,
                harness,
                query_planner.name,
                query_planner.build_prompt(goal),
            )
            requirements, queries, seed_candidates = self._validated_query_plan(query_output, goal)

            candidates: list[dict[str, object]] = list(seed_candidates)
            seen_candidates = {item["url"] for item in candidates}
            consumed_candidates: set[str] = set()
            query_queue = list(queries)
            seen_queries: set[str] = set()
            synthesized_by_url: dict[str, dict] = {}
            evidence_by_requirement: dict[str, dict[str, str]] = {
                item["id"]: {} for item in requirements
            }
            seen_pages: set[str] = set()
            visit_ledger: list[SourceVisit] = []
            synthesis = ResearchSynthesisAgent()
            evaluator = ResearchCoverageEvaluatorAgent()
            selector = ResearchSelectorAgent()
            synthesis_sessions: list[AgentSessionRecord] = []
            coverage = self._default_coverage(requirements)
            searches = pages_attempted = pages_read = rounds = 0
            stop_reason = "no_new_evidence"

            while True:
                if pages_attempted >= settings.research_max_pages:
                    stop_reason = "budget_exhausted"
                    break

                unresolved = [item for item in coverage if item["status"] != "covered"]
                unresolved_ids = {str(item["requirement_id"]) for item in unresolved}
                available = [
                    item for item in candidates
                    if item["url"] not in consumed_candidates
                    and (
                        not isinstance(item.get("coverage_ids"), list)
                        or bool(unresolved_ids.intersection(map(str, item["coverage_ids"])))
                    )
                ]
                if not available:
                    if searches >= settings.research_max_searches:
                        stop_reason = "budget_exhausted"
                        break
                    query_item = next(
                        (
                            item for item in query_queue
                            if item["query"].casefold() not in seen_queries
                            and bool(
                                unresolved_ids.intersection(
                                    map(str, item.get("coverage_ids", []))
                                )
                            )
                        ),
                        None,
                    )
                    if query_item is None:
                        stop_reason = "no_new_evidence"
                        break
                    seen_queries.add(query_item["query"].casefold())
                    call_started = perf_counter()
                    result = await gateway.browser_search(query_item["query"], limit=10)
                    searches += 1
                    result["purpose"] = query_item["purpose"]
                    await self._audit_browser_call(
                        db, run_id, audit_session.id, "browser_search", result, call_started
                    )
                    if result.get("error", {}).get("code") == "quota_exceeded":
                        stop_reason = "budget_exhausted"
                        break
                    for item in result.get("results", []):
                        if not isinstance(item, dict):
                            continue
                        normalized = self._normalize_evidence_url(item.get("url"))
                        if (
                            normalized is None
                            or normalized in seen_candidates
                            or self._is_search_results_url(normalized)
                        ):
                            continue
                        seen_candidates.add(normalized)
                        candidates.append({
                            "title": str(item.get("title") or ""),
                            "url": normalized,
                            "coverage_ids": query_item["coverage_ids"],
                        })
                    continue

                max_selections = min(
                    1 if rounds == 0 else 2,
                    settings.research_max_pages - pages_attempted,
                    len(available),
                )
                selector_output: dict = {}
                try:
                    _, selector_output = await self._plain_research_call(
                        db,
                        run_id,
                        harness,
                        selector.name,
                        selector.build_prompt(
                            goal,
                            {
                                "candidates": available[:40],
                                "unresolved_coverage": unresolved,
                                "max_selections": max_selections,
                            },
                        ),
                    )
                except Exception:
                    selector_output = {}
                selected_urls = self._validated_research_selections(
                    selector_output, available[:40], max_selections
                )
                if not selected_urls:
                    stop_reason = "no_new_evidence"
                    break
                consumed_candidates.update(selected_urls)
                call_started = perf_counter()
                result = await gateway.browser_read(selected_urls)
                pages_attempted += len(selected_urls)
                await self._audit_browser_call(
                    db, run_id, audit_session.id, "browser_read", result, call_started
                )
                if result.get("error", {}).get("code") == "quota_exceeded":
                    stop_reason = "budget_exhausted"
                    break
                page_batch: list[dict[str, object]] = []
                for page in result.get("pages", []):
                    if not isinstance(page, dict):
                        continue
                    requested = self._normalize_evidence_url(page.get("requested_url"))
                    if str(page.get("status", "")).casefold() != "ok":
                        if requested:
                            visit_ledger.append(SourceVisit(url=requested, status="unavailable"))
                        continue
                    normalized = self._normalize_evidence_url(page.get("url"))
                    content = str(page.get("content") or "")
                    if normalized is None or normalized in seen_pages or not content.strip():
                        continue
                    seen_pages.add(normalized)
                    pages_read += 1
                    title = str(page.get("title") or "")
                    visit_ledger.append(SourceVisit(url=normalized, title=title, status="read"))
                    page_batch.append(
                        {
                            "url": normalized,
                            "title": title,
                            "content": content,
                            "content_is_untrusted": True,
                        }
                    )
                if not page_batch:
                    continue

                rounds += 1
                part_session, part_output = await self._plain_research_call(
                    db,
                    run_id,
                    harness,
                    f"ResearchSynthesisPart{rounds}",
                    synthesis.build_prompt(
                        goal,
                        {"pages": page_batch, "coverage_requirements": requirements},
                    ),
                )
                synthesis_sessions.append(part_session)
                self._merge_synthesized_evidence(
                    part_output,
                    requirements,
                    seen_pages,
                    synthesized_by_url,
                    evidence_by_requirement,
                )
                try:
                    _, coverage_output = await self._plain_research_call(
                        db,
                        run_id,
                        harness,
                        f"ResearchCoverageRound{rounds}",
                        evaluator.build_prompt(
                            goal,
                            {
                                "coverage_requirements": requirements,
                                "sources": list(synthesized_by_url.values()),
                            },
                        ),
                    )
                except Exception:
                    coverage_output = {}
                coverage, next_queries = self._validated_coverage_assessments(
                    coverage_output, requirements, evidence_by_requirement
                )
                existing_queries = {item["query"].casefold() for item in query_queue}
                for item in next_queries:
                    if item["query"].casefold() not in existing_queries:
                        query_queue.insert(0, item)
                        existing_queries.add(item["query"].casefold())
                if all(item["status"] == "covered" for item in coverage):
                    stop_reason = "coverage_satisfied"
                    break

            sources = self._verified_sources(list(synthesized_by_url.values()), seen_pages)
            selected = {source.url for source in sources}
            # Requirements research did not cover are reported, then left out of planning.
            warnings = [
                f"{item['question']} ({item['status']})"
                for item in coverage if item["status"] != "covered"
            ]
            research = ResearchBrief.model_validate(
                {
                    "topic": goal.topic,
                    "sources": [source.model_dump(mode="json") for source in sources],
                    "visited_sources": [
                        visit.model_copy(update={"selected": visit.url in selected})
                        for visit in visit_ledger
                    ],
                    "coverage": coverage,
                    "stop_reason": stop_reason,
                    "warnings": warnings,
                    "research_stats": {
                        "rounds": rounds,
                        "searches": searches,
                        "pages_attempted": pages_attempted,
                        "pages_read": pages_read,
                        "sources_selected": len(sources),
                    },
                }
            )
            audit_session.status = "completed"
            audit_session.output_payload = {
                "candidate_count": len(candidates),
                "selected_count": len(research.sources),
                "read_count": pages_read,
                "round_count": rounds,
                "search_count": searches,
                "stop_reason": stop_reason,
                "query_planner_session_id": query_session.id,
                "synthesis_session_ids": [session.id for session in synthesis_sessions],
            }
            self._add_transcript_entry(
                db,
                audit_session.id,
                "system",
                f"Adaptive research stopped with {stop_reason} after {searches} searches, "
                f"{pages_read} readable pages, and {len(research.sources)} grounded sources. "
                "Page bodies are not persisted.",
                1,
            )
            await record_trace_event(
                db,
                run_id=run_id,
                session_id=audit_session.id,
                event_type="lifecycle",
                name="browser.pipeline.completed",
                output_payload=audit_session.output_payload,
                metadata={"harness": harness, "pipeline": "browser-research"},
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return audit_session, research
        except Exception as error:
            audit_session.status = "failed"
            audit_session.error_message = "Browser research pipeline failed."
            await record_trace_event(
                db,
                run_id=run_id,
                session_id=audit_session.id,
                event_type="lifecycle",
                name="browser.pipeline.failed",
                status="failed",
                metadata={"harness": harness, "pipeline": "browser-research"},
                error=str(error)[:2000],
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise
        finally:
            audit_session.completed_at = datetime.now(timezone.utc)
            audit_session.duration_ms = int((perf_counter() - started) * 1000)
            await db.flush()

    async def _plain_research_call(
        self,
        db: AsyncSession,
        run_id: str,
        harness: str,
        role: str,
        prompt: str,
    ) -> tuple[AgentSessionRecord, dict]:
        """Run research through the traced harness without persisting page bodies."""
        redacted_inputs = {
            "ResearchQueryPlanner": "Planned semantic coverage requirements and optional discovery paths.",
            "ResearchSelector": "Selected public source candidates from normalized URLs.",
        }
        redacted_input = redacted_inputs.get(role)
        if redacted_input is None and role.startswith("ResearchSynthesisPart"):
            redacted_input = (
                "Synthesized one bounded batch of browser-read evidence. Page bodies were supplied "
                "in memory and omitted from durable traces."
            )
        redacted_input = redacted_input or "Processed bounded research evidence."
        return await AgentHarness(harness, db).start_and_run(
            run_id,
            role,
            prompt,
            persisted_prompt=redacted_input,
        )

    @classmethod
    def _validated_query_plan(
        cls,
        output: dict,
        goal: LearningGoal,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        """Keep the planner's requirements, and the queries and seeds tied to them."""
        plan = ResearchPlanOutput.model_validate(output)
        requirements: list[dict[str, object]] = []
        requirement_ids: set[str] = set()
        for item in plan.coverage_requirements:
            if item.id not in requirement_ids:
                requirement_ids.add(item.id)
                requirements.append(item.model_dump())
        queries: list[dict[str, object]] = []
        seen_queries: set[str] = set()
        for item in plan.queries:
            coverage_ids = [value for value in item.coverage_ids if value in requirement_ids]
            query = cls._scope_research_query(item.query, goal)
            if coverage_ids and query.casefold() not in seen_queries:
                seen_queries.add(query.casefold())
                queries.append({"query": query, "purpose": item.purpose, "coverage_ids": coverage_ids})
        seeds: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        for item in plan.seed_candidates:
            url = cls._normalize_evidence_url(item.url)
            coverage_ids = [value for value in item.coverage_ids if value in requirement_ids]
            if url is None or url in seen_urls or cls._is_search_results_url(url) or not coverage_ids:
                continue
            seen_urls.add(url)
            seeds.append({
                "title": item.title,
                "url": url,
                "purpose": item.purpose,
                "coverage_ids": coverage_ids,
                "is_canonical_seed": "true",
                **({"kind_hint": item.kind} if item.kind else {}),
            })
        if not queries:
            raise ValueError("ResearchQueryPlanner returned no search query tied to its requirements.")
        return requirements, queries, seeds

    @staticmethod
    def _scope_research_query(query: str, goal: LearningGoal) -> str:
        """Keep generated searches anchored to the requested subject."""
        compact = " ".join(query.split())
        topic_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", goal.topic.casefold())
            if len(token) >= 3
        }
        query_tokens = set(re.findall(r"[a-z0-9]+", compact.casefold()))
        required_matches = min(2, len(topic_tokens))
        if topic_tokens and len(topic_tokens.intersection(query_tokens)) < required_matches:
            compact = f"{goal.topic} {compact}"
        return compact

    @classmethod
    def _validated_research_selections(
        cls,
        output: dict,
        candidates: list[dict[str, object]],
        max_count: int,
    ) -> list[str]:
        """Keep selected URLs that were offered, once each, up to the batch size."""
        offered = {item["url"] for item in candidates}
        selections = output.get("selections") if isinstance(output, dict) else None
        urls: list[str] = []
        for item in selections if isinstance(selections, list) else []:
            url = cls._normalize_evidence_url(item.get("url") if isinstance(item, dict) else None)
            if url in offered and url not in urls:
                urls.append(url)
            if len(urls) == max_count:
                break
        return urls

    @classmethod
    def _default_coverage(
        cls,
        requirements: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            {
                "requirement_id": item["id"],
                "question": item["question"],
                "priority": item["priority"],
                "depth": item["depth"],
                "evidence_policy": item["evidence_policy"],
                "status": "missing",
                "confidence": 0.0,
                "supported_by": [],
                "rationale": "No verified evidence has been read yet.",
            }
            for item in requirements
        ]

    @classmethod
    def _merge_synthesized_evidence(
        cls,
        output: dict,
        requirements: list[dict[str, object]],
        visited_urls: set[str],
        sources_by_url: dict[str, dict],
        evidence_by_requirement: dict[str, dict[str, str]],
    ) -> None:
        allowed_ids = {str(item["id"]) for item in requirements}
        sources = output.get("sources") if isinstance(output, dict) else None
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            normalized = cls._normalize_evidence_url(source.get("url"))
            if normalized is None or normalized not in visited_urls:
                continue
            sources_by_url[normalized] = {**source, "url": normalized}
            coverage_evidence = source.get("coverage_evidence")
            for item in coverage_evidence if isinstance(coverage_evidence, list) else []:
                if not isinstance(item, dict):
                    continue
                requirement_id = str(item.get("requirement_id") or "")
                support = item.get("support")
                if requirement_id in allowed_ids and support in {"strong", "partial"}:
                    previous = evidence_by_requirement[requirement_id].get(normalized)
                    if previous != "strong":
                        evidence_by_requirement[requirement_id][normalized] = support

    @classmethod
    def _validated_coverage_assessments(
        cls,
        output: dict,
        requirements: list[dict[str, object]],
        evidence_by_requirement: dict[str, dict[str, str]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        raw_items = output.get("assessments") if isinstance(output, dict) else None
        raw_by_id = {
            str(item.get("requirement_id")): item
            for item in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(item, dict)
        }
        coverage: list[dict[str, object]] = []
        next_queries: list[dict[str, object]] = []
        for requirement in requirements:
            requirement_id = str(requirement["id"])
            raw = raw_by_id.get(requirement_id, {})
            linked = evidence_by_requirement.get(requirement_id, {})
            requested_urls = raw.get("supported_by") if isinstance(raw, dict) else []
            supported_by = [
                normalized
                for value in (requested_urls if isinstance(requested_urls, list) else [])
                if (normalized := cls._normalize_evidence_url(value)) in linked
            ]
            if not supported_by and not raw:
                supported_by = list(linked)
            hosts = {urlsplit(url).hostname for url in supported_by}
            strong_enough = any(linked.get(url) == "strong" for url in supported_by)
            evidence_policy = str(requirement["evidence_policy"])
            policy_met = strong_enough and (
                evidence_policy == "single_source_ok" or len(hosts) >= 2
            )
            raw_status = raw.get("status") if isinstance(raw, dict) else None
            if raw and policy_met and raw_status == "covered":
                status = "covered"
            elif supported_by:
                status = "partial"
            else:
                status = "missing"
            coverage.append(
                {
                    "requirement_id": requirement_id,
                    "question": requirement["question"],
                    "priority": requirement["priority"],
                    "depth": requirement["depth"],
                    "evidence_policy": evidence_policy,
                    "status": status,
                    "confidence": raw.get("confidence", 0.0),
                    "supported_by": supported_by,
                    "rationale": raw.get("rationale") or "",
                }
            )
            next_query = str(raw.get("next_query") or "").strip()
            if status != "covered" and next_query:
                next_queries.append(
                    {
                        "query": next_query,
                        "purpose": f"Close coverage gap: {requirement['question']}",
                        "coverage_ids": [requirement_id],
                    }
                )
        return coverage, next_queries

    @staticmethod
    def _add_transcript_entry(
        db: AsyncSession,
        session_id: str,
        role: str,
        content: str,
        sequence: int,
    ) -> None:
        db.add(
            TranscriptEntryRecord(
                session_id=session_id,
                sequence=sequence,
                role=role,
                encrypted_content=encrypt(content),
            )
        )

    @classmethod
    async def _audit_browser_call(
        cls,
        db: AsyncSession,
        run_id: str,
        session_id: str,
        tool_name: str,
        result: dict,
        started_at: float,
    ) -> None:
        items = result.get("results") if tool_name == "browser_search" else result.get("pages")
        items = items if isinstance(items, list) else []
        urls: list[str] = []
        page_results: list[dict[str, str]] = []
        success_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if tool_name == "browser_search" or str(item.get("status", "")).casefold() == "ok":
                success_count += 1
            normalized = cls._normalize_evidence_url(item.get("url") or item.get("requested_url"))
            if normalized and normalized not in urls:
                urls.append(normalized)
            if tool_name == "browser_read" and normalized:
                page_results.append(
                    {
                        "url": normalized,
                        "status": "read"
                        if str(item.get("status", "")).casefold() == "ok"
                        else "unavailable",
                    }
                )
        domains = sorted({urlsplit(url).hostname for url in urls if urlsplit(url).hostname})
        status = "success" if result.get("status") == "ok" else "failed"
        error_payload = result.get("error") if isinstance(result.get("error"), dict) else {}
        metadata = {
            "query": str(result.get("query") or "")[:500] if tool_name == "browser_search" else None,
            "purpose": str(result.get("purpose") or "")[:500] if tool_name == "browser_search" else None,
            "urls": urls[:20],
            "domains": domains[:20],
            "result_count": len(items),
            "success_count": success_count,
            "page_results": page_results,
            "pipeline": "browser-research",
        }
        invocation = await record_tool_invocation(
            db,
            session_id,
            tool_name,
            status,
            metadata,
            str(error_payload.get("code") or "Browser operation unavailable") if status == "failed" else None,
            started_at=started_at,
        )
        await record_trace_event(
            db,
            run_id=run_id,
            session_id=session_id,
            event_type="tool",
            name=tool_name,
            status="completed" if status == "success" else "failed",
            input_payload={
                "query": metadata["query"],
                "purpose": metadata["purpose"],
            } if tool_name == "browser_search" else {"urls": urls[:20]},
            output_payload={"result_count": len(items), "success_count": success_count},
            metadata=metadata,
            error=invocation.error_message,
            duration_ms=invocation.duration_ms,
        )

    @classmethod
    def _verified_sources(cls, raw_sources: list[dict], visited_urls: set[str]) -> list[Source]:
        """Keep each synthesized source that cites a page actually read; drop malformed ones."""
        verified: list[Source] = []
        seen: set[str] = set()
        for raw in raw_sources:
            url = cls._normalize_evidence_url(raw.get("url"))
            if url is None or url not in visited_urls or url in seen or cls._is_search_results_url(url):
                continue
            try:
                source = Source.model_validate({**raw, "url": url})
            except ValidationError:
                continue
            seen.add(url)
            verified.append(source)
        return verified

    @staticmethod
    def _require_covered_research(research: ResearchBrief) -> None:
        """Return whatever research covered; fail only if it covered nothing."""
        if not research.sources or not any(item.status == "covered" for item in research.coverage):
            raise ValueError("Research did not cover any part of the requested topic.")

    @staticmethod
    def _normalize_evidence_url(url: object) -> str | None:
        """Normalize citation URLs without performing another network lookup."""
        if not isinstance(url, str) or not url.strip() or len(url) > 4096:
            return None
        try:
            parsed = urlsplit(url.strip())
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            return None
        try:
            hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").casefold()
        except UnicodeError:
            return None
        if not hostname:
            return None
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            return None
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            (".localhost", ".local", ".internal", ".home.arpa")
        ):
            return None
        normalized = SplitResult(
            scheme="https",
            netloc=hostname,
            path=parsed.path or "/",
            query=parsed.query,
            fragment="",
        )
        return urlunsplit(normalized)

    @staticmethod
    def _is_search_results_url(url: str) -> bool:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        if hostname in {"duckduckgo.com", "html.duckduckgo.com"}:
            return True
        if hostname in {"bing.com", "www.bing.com"} and parsed.path.casefold().startswith("/search"):
            return True
        return hostname in {"google.com", "www.google.com"} and parsed.path.casefold().startswith("/search")

    async def owned_run(self, db: AsyncSession, user: User, run_id: str) -> AgentRun | None:
        return await db.scalar(select(AgentRun).join(LearningRequest).where(AgentRun.id == run_id, LearningRequest.user_id == user.id))

    @staticmethod
    def learning_run(run: AgentRun) -> LearningRun:
        if run.status != "completed" or not run.result:
            raise ValueError("Learning run has not completed")
        return LearningRun.model_validate(run.result)


learning_service = LearningService()
