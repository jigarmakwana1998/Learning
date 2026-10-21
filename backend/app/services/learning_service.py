import ipaddress
import json
import logging
import math
import re
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    ChapterPlannerAgent, LessonWriterAgent, PlannerAgent, ResearchCoverageEvaluatorAgent,
    ResearchQueryPlannerAgent, ResearchSelectorAgent, ResearchSynthesisAgent,
)
from app.agents.contracts import PlannerOutput, ResearchPlanOutput
from app.browser.gateway import BrowserGateway
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import encrypt
from app.harness import AgentHarness
from app.mcp.audit import record_tool_invocation, record_trace_event
from app.models.database import (
    AgentRun, AgentSessionRecord, AssignmentSubmissionRecord, LearningRequest,
    LessonProgressRecord, QuizSubmissionRecord, TranscriptEntryRecord, User,
)
from app.schemas.learning import (
    AssignmentSubmissionResponse, Course, CurriculumModule,
    LearningGoal, LearningProgressResponse, LearningRun, LearningRunRequest, Lesson,
    QuizQuestionFeedback, QuizSubmissionResponse, ResearchBrief, Source,
    SourceVisit,
)

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
        harness_name = run.harness
        harness = AgentHarness(harness_name, db)
        try:
            research_session, research = await self._browser_research(
                db, run.id, harness_name, goal
            )
            self._require_covered_research(research)
            plan, planner_sessions = await self._plan_course(harness, run.id, goal, research)
            # The planner returns structure only; turn chapters into modules and
            # sections into lesson drafts that the lesson writer expands.
            planned = {"curriculum": self._planned_modules(goal, plan, research)}
            planned, writer_sessions = await self._expand_short_lessons(
                harness, run.id, goal, research, planned
            )
            curriculum = self._provider_curriculum(goal, planned, research)
            # Assessments come from a dedicated agent in a later step.
            result = LearningRun(
                id=run.id, harness=harness_name, research=research, curriculum=curriculum,
                course=Course(
                    title=f"{goal.topic} learning path",
                    modules=curriculum,
                    warnings=self._time_budget_warnings(goal, curriculum),
                ),
                sessions={
                    "Researcher": research_session.id,
                    **planner_sessions,
                    **writer_sessions,
                },
            )
            result.id = run.id
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return self.public_learning_run(result)
        except Exception as error:
            detail = str(error) if isinstance(error, RuntimeError | ValueError) else "Course generation failed"
            run.status, run.result, run.completed_at = "failed", {"error": detail}, datetime.now(timezone.utc)
            await db.commit()
            raise

    async def _plan_course(
        self,
        harness: AgentHarness,
        run_id: str,
        goal: LearningGoal,
        research: ResearchBrief,
    ) -> tuple[dict, dict[str, str]]:
        """Plan in two small steps: the chapter outline, then each chapter's sections in order.

        Each chapter call sees the whole outline and the sections already planned, so
        nothing is lost by splitting the work into smaller outputs.
        """
        outliner, chapter_planner = PlannerAgent(), ChapterPlannerAgent()
        outline_session, outline = await harness.start_and_run(
            run_id, outliner.name, outliner.build_prompt(goal, research.model_dump())
        )
        sessions = {"Planner": outline_session.id}
        coverage_by_id = {item.requirement_id: item for item in research.coverage}
        remaining_minutes = goal.weeks * goal.hours_per_week * 60
        chapters: list[dict] = []
        for number, chapter in enumerate(outline["chapters"], start=1):
            # Fair share of what is left, so early chapters cannot starve later ones.
            chapters_left = len(outline["chapters"]) - number + 1
            chapter_minutes = max(remaining_minutes, 0) // chapters_left
            targets = [coverage_by_id[i] for i in chapter["coverage_ids"] if i in coverage_by_id]
            supporting_urls = {url for target in targets for url in target.supported_by}
            role = f"{chapter_planner.name}{number}"
            session, output = await harness.start_and_run(
                run_id,
                role,
                chapter_planner.build_prompt(
                    goal,
                    {
                        "outline": [
                            {"number": index, "title": item["title"], "summary": item["summary"]}
                            for index, item in enumerate(outline["chapters"], start=1)
                        ],
                        "chapter": {"number": number, **chapter},
                        "planned_sections": [
                            {"chapter": index, "sections": [section["title"] for section in item["sections"]]}
                            for index, item in enumerate(chapters, start=1)
                        ],
                        "research": {
                            "coverage": [target.model_dump(mode="json") for target in targets],
                            "sources": [
                                source.model_dump(mode="json")
                                for source in research.sources
                                if source.url in supporting_urls
                            ],
                        },
                        "chapter_minutes": chapter_minutes,
                    },
                ),
            )
            sessions[role] = session.id
            chapters.append({**chapter, "sections": output["sections"]})
            remaining_minutes -= sum(section["estimated_minutes"] for section in output["sections"])
        return {"chapters": chapters}, sessions

    async def _expand_short_lessons(
        self,
        harness: AgentHarness,
        run_id: str,
        goal: LearningGoal,
        research: ResearchBrief,
        planner_output: dict,
    ) -> tuple[dict, dict[str, str]]:
        """Have the lesson writer expand every planned section into cited paragraphs."""
        expanded_output = json.loads(json.dumps(planner_output))
        writer = LessonWriterAgent()
        sessions: dict[str, str] = {}
        coverage_by_id = {item.requirement_id: item for item in research.coverage}
        for module in expanded_output["curriculum"]:
            for lesson in module["lessons"]:
                coverage_targets = [
                    coverage_by_id[requirement_id].model_dump(mode="json")
                    for requirement_id in lesson["coverage_ids"]
                ]
                target_urls = {url for target in coverage_targets for url in target["supported_by"]}
                verified_sources = [
                    source.model_dump(mode="json")
                    for source in research.sources
                    if not target_urls or source.url in target_urls
                ]
                session, output = await harness.start_and_run(
                    run_id,
                    writer.name,
                    writer.build_prompt(
                        goal,
                        {
                            "module": {
                                "week": module["week"],
                                "title": module["title"],
                                "outcomes": module["outcomes"],
                            },
                            "lesson_draft": lesson,
                            "coverage_targets": coverage_targets,
                            "verified_sources": verified_sources,
                        },
                    ),
                )
                expanded = output.get("lesson") if isinstance(output, dict) else None
                if not isinstance(expanded, dict) or str(expanded.get("id")) != lesson["id"]:
                    raise ValueError(f"LessonWriter must return the requested lesson id {lesson['id']}.")
                lesson["paragraphs"] = expanded.get("paragraphs") or []
                sessions[f"LessonWriter:{lesson['id']}"] = session.id
        return expanded_output, sessions

    async def _browser_research(
        self,
        db: AsyncSession,
        run_id: str,
        harness: str,
        goal: LearningGoal,
    ) -> tuple[AgentSessionRecord, ResearchBrief]:
        """Browse until semantic coverage is complete or a safety boundary is reached."""
        gateway = self.browser_gateway_factory()
        settings = get_settings()
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

    @classmethod
    def _planned_modules(
        cls,
        goal: LearningGoal,
        planner_output: dict,
        research: ResearchBrief,
    ) -> list[dict]:
        """Turn the planner's chapters into modules and its sections into lesson drafts.

        The schema already enforces required fields; here we only check what it cannot:
        coverage ids must be ones research covered, every covered requirement needs a
        section, and the course must fit the learner's time budget.
        """
        try:
            plan = PlannerOutput.model_validate(planner_output)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Planner returned an invalid chapter structure: {error}") from error
        covered = {item.requirement_id for item in research.coverage if item.status == "covered"}
        assigned: set[str] = set()
        modules = []
        for chapter_number, chapter in enumerate(plan.chapters, start=1):
            lessons = []
            for section_number, section in enumerate(chapter.sections, start=1):
                if unknown := [item for item in section.coverage_ids if item not in covered]:
                    raise ValueError(
                        f"Planner chapter {chapter_number} section {section_number} uses coverage ids "
                        f"that research did not cover: {', '.join(unknown)}"
                    )
                assigned.update(section.coverage_ids)
                lessons.append({
                    "id": f"chapter-{chapter_number}-section-{section_number}",
                    "title": section.title,
                    "objective": section.objective,
                    "coverage_ids": list(dict.fromkeys(section.coverage_ids)),
                    "section_plan": section.key_points,
                    "paragraphs": [],
                    "estimated_minutes": section.estimated_minutes,
                })
            minutes = sum(lesson["estimated_minutes"] for lesson in lessons)
            modules.append({
                "week": chapter_number,  # chapter number; the field name predates chapters
                # Chapters are numbered by the app; drop a model-added "Chapter 3:" prefix.
                "title": re.sub(r"^\s*chapter\s+\d+\s*[:.\-\u2013\u2014]\s*", "", chapter.title, flags=re.IGNORECASE),
                "overview": chapter.summary,
                "outcomes": [lesson["objective"] for lesson in lessons],
                "coverage_ids": list(dict.fromkeys(i for lesson in lessons for i in lesson["coverage_ids"])),
                "source_urls": [],
                "estimated_hours": max(1, math.ceil(minutes / 60)),
                "lessons": lessons,
            })
        if missing := sorted(covered - assigned):
            raise ValueError(f"Planner left covered research requirements without a section: {', '.join(missing)}")
        return modules

    @staticmethod
    def _time_budget_warnings(goal: LearningGoal, modules: list[CurriculumModule]) -> list[str]:
        """Soft limit: section minutes are model estimates, so an overrun is a warning, never a failure."""
        budget = goal.weeks * goal.hours_per_week * 60
        planned = sum(lesson.estimated_minutes for module in modules for lesson in module.lessons)
        if planned <= budget:
            return []
        return [
            f"Planned sections total {planned} minutes, over the {budget}-minute budget "
            f"({goal.weeks} weeks x {goal.hours_per_week} h)."
        ]

    @classmethod
    def _provider_curriculum(
        cls,
        goal: LearningGoal,
        planner_output: dict,
        research: ResearchBrief,
    ) -> list[CurriculumModule]:
        """Validate complete provider-authored lessons and their evidence links."""
        try:
            modules = [CurriculumModule.model_validate(item) for item in planner_output["curriculum"]]
        except (TypeError, ValueError) as error:
            raise ValueError(f"Lesson writer returned an invalid lesson structure: {error}") from error

        verified_sources = {source.url: source for source in research.sources}
        verified_urls = set(verified_sources)
        coverage_by_id = {item.requirement_id: item for item in research.coverage}
        covered_ids = {key for key, item in coverage_by_id.items() if item.status == "covered"}
        coverage_support = {
            requirement_id: {
                normalized
                for url in item.supported_by
                if (normalized := cls._normalize_evidence_url(url)) is not None
            }
            for requirement_id, item in coverage_by_id.items()
        }
        course_coverage_ids: set[str] = set()
        grounded: list[CurriculumModule] = []
        for module in sorted(modules, key=lambda item: item.week):
            module_coverage_ids = cls._grounded_coverage_ids(
                module.coverage_ids,
                coverage_by_id,
                f"module week {module.week}",
            ) if coverage_by_id else []
            lessons: list[Lesson] = []
            for lesson in module.lessons:
                if len(lesson.paragraphs) != len(lesson.section_plan):
                    raise ValueError(
                        f"Lesson {lesson.id} must have one paragraph per key point "
                        f"({len(lesson.section_plan)}), got {len(lesson.paragraphs)}."
                    )
                lesson_coverage_ids = cls._grounded_coverage_ids(
                    lesson.coverage_ids,
                    coverage_by_id,
                    f"lesson {lesson.id}",
                ) if coverage_by_id else []
                paragraphs = []
                paragraph_urls: list[str] = []
                paragraph_coverage_ids: set[str] = set()
                for index, paragraph in enumerate(lesson.paragraphs, start=1):
                    urls = cls._grounded_source_urls(
                        paragraph.source_urls,
                        verified_urls,
                        f"lesson {lesson.id} paragraph {index}",
                    )
                    coverage_ids = cls._grounded_coverage_ids(
                        paragraph.coverage_ids,
                        coverage_by_id,
                        f"lesson {lesson.id} paragraph {index}",
                    ) if coverage_by_id else []
                    if coverage_by_id and not set(coverage_ids).issubset(set(lesson_coverage_ids)):
                        raise ValueError(
                            f"Planner lesson {lesson.id} paragraph {index} declares coverage outside its lesson."
                        )
                    for requirement_id in coverage_ids:
                        if not coverage_support[requirement_id].intersection(urls):
                            raise ValueError(
                                f"Planner lesson {lesson.id} paragraph {index} does not cite evidence "
                                f"supporting coverage requirement {requirement_id}."
                            )
                        paragraph_coverage_ids.add(requirement_id)
                    for url in urls:
                        if url not in paragraph_urls:
                            paragraph_urls.append(url)
                    paragraphs.append(
                        paragraph.model_copy(
                            update={"coverage_ids": coverage_ids, "source_urls": urls}
                        )
                    )
                if coverage_by_id and paragraph_coverage_ids != set(lesson_coverage_ids):
                    raise ValueError(
                        f"Planner lesson {lesson.id} must teach every declared coverage requirement in a cited paragraph."
                    )
                lesson_urls = cls._grounded_source_urls(
                    lesson.source_urls or paragraph_urls,
                    verified_urls,
                    f"lesson {lesson.id}",
                )
                if not set(paragraph_urls).issubset(set(lesson_urls)):
                    lesson_urls = [*lesson_urls, *(url for url in paragraph_urls if url not in lesson_urls)]
                lessons.append(
                    lesson.model_copy(
                        update={
                            "content": "\n\n".join(paragraph.text.strip() for paragraph in paragraphs),
                            "paragraphs": paragraphs,
                            "coverage_ids": lesson_coverage_ids,
                            "source_urls": lesson_urls,
                        }
                    )
                )
            lesson_coverage_union = {
                requirement_id
                for lesson in lessons
                for requirement_id in lesson.coverage_ids
            }
            if coverage_by_id and lesson_coverage_union != set(module_coverage_ids):
                raise ValueError(
                    f"Planner module week {module.week} coverage_ids must equal the union of its lessons."
                )
            course_coverage_ids.update(lesson_coverage_union)
            # A chapter's sources are the ones its sections actually cite.
            module_urls = cls._grounded_source_urls(
                list(dict.fromkeys(url for lesson in lessons for url in lesson.source_urls)),
                verified_urls,
                f"chapter {module.week}",
            )
            grounded.append(
                module.model_copy(
                    update={
                        "coverage_ids": module_coverage_ids,
                        "source_urls": module_urls,
                        "lessons": lessons,
                    }
                )
            )
        if coverage_by_id and course_coverage_ids != covered_ids:
            missing = sorted(covered_ids - course_coverage_ids)
            raise ValueError(
                "Planner curriculum does not cover every verified research requirement: "
                + ", ".join(missing)
            )
        return grounded

    @staticmethod
    def _require_covered_research(research: ResearchBrief) -> None:
        """Generate a course from whatever research covered; stop only if it covered nothing."""
        if not research.sources or not any(item.status == "covered" for item in research.coverage):
            raise ValueError("Research did not cover any part of the requested topic, so no course was generated.")

    @classmethod
    def _grounded_source_urls(
        cls,
        urls: list[str],
        verified_urls: set[str],
        owner: str,
    ) -> list[str]:
        normalized_urls: list[str] = []
        for raw_url in urls:
            normalized = cls._normalize_evidence_url(raw_url)
            if normalized is None or normalized not in verified_urls:
                raise ValueError(f"Planner cited an unverified source URL in {owner}.")
            if normalized not in normalized_urls:
                normalized_urls.append(normalized)
        if not normalized_urls:
            raise ValueError(f"Planner must cite at least one verified source URL in {owner}.")
        return normalized_urls

    @staticmethod
    def _grounded_coverage_ids(
        coverage_ids: list[str],
        coverage_by_id: dict[str, object],
        owner: str,
    ) -> list[str]:
        grounded: list[str] = []
        for raw_id in coverage_ids:
            requirement_id = str(raw_id)
            coverage = coverage_by_id.get(requirement_id)
            if coverage is None or getattr(coverage, "status", None) != "covered":
                raise ValueError(
                    f"Planner referenced an unverified coverage requirement in {owner}."
                )
            if requirement_id not in grounded:
                grounded.append(requirement_id)
        if not grounded:
            raise ValueError(f"Planner must assign at least one coverage requirement to {owner}.")
        return grounded

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

    @staticmethod
    def public_learning_run(run: LearningRun) -> LearningRun:
        """Never reveal answer keys before a learner has submitted the quiz."""
        if run.assessment is None:
            return run
        quiz_items = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz_items]
        legacy_quiz = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz]
        assessment = run.assessment.model_copy(update={"quiz_items": quiz_items, "quiz": legacy_quiz})
        return run.model_copy(update={"assessment": assessment})

    async def submit_quiz(self, db: AsyncSession, user: User, run: AgentRun, answers: list[tuple[str, str]]) -> QuizSubmissionResponse:
        course = self.learning_run(run)
        if course.assessment is None:
            raise ValueError("This course has no quiz yet; assessments are generated in a later step.")
        questions = course.assessment.quiz_items or course.assessment.quiz
        by_id = {question.id: question for question in questions}
        supplied = dict(answers)
        if unknown := set(supplied) - set(by_id):
            raise ValueError(f"Unknown quiz question: {min(unknown)}")
        feedback = [
            QuizQuestionFeedback(
                question_id=question.id, selected_answer=supplied.get(question.id),
                correct=supplied.get(question.id) == question.correct_answer,
                correct_answer=question.correct_answer or "", explanation=question.explanation or "",
            )
            for question in questions
        ]
        correct_count = sum(item.correct for item in feedback)
        score = round(correct_count * 100 / len(questions)) if questions else 0
        record = QuizSubmissionRecord(
            agent_run_id=run.id, user_id=user.id, answers=supplied, score_percent=score,
            feedback=[item.model_dump(mode="json") for item in feedback],
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return QuizSubmissionResponse(id=record.id, run_id=run.id, score_percent=score, correct_count=correct_count, total_questions=len(questions), feedback=feedback, submitted_at=record.submitted_at)

    async def submit_work(self, db: AsyncSession, user: User, run: AgentRun, kind: str, content: str) -> AssignmentSubmissionResponse:
        course = self.learning_run(run)
        if course.assessment is None:
            raise ValueError("This course has no assignment yet; assessments are generated in a later step.")
        expected = course.assessment.assignment.deliverables if kind == "assignment" else ["A working outcome", "A short decision log", "Validation evidence", "A reflection"]
        word_count = len(content.split())
        status = "accepted" if word_count >= 120 else "needs_revision"
        feedback = [
            f"Submitted {word_count} words for the {kind}.",
            f"To strengthen it, make sure it includes: {expected[0].lower()}.",
            "Add a concrete observation or artifact that lets another learner verify your result.",
        ]
        record = AssignmentSubmissionRecord(agent_run_id=run.id, user_id=user.id, kind=kind, content=content, status=status, feedback=feedback)
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return AssignmentSubmissionResponse(id=record.id, run_id=run.id, kind=kind, content=content, status=status, feedback=feedback, submitted_at=record.submitted_at)

    async def set_progress(self, db: AsyncSession, user: User, run: AgentRun, lesson_id: str, completed: bool) -> LearningProgressResponse:
        course = self.learning_run(run)
        lessons = [lesson for module in (course.course.modules if course.course else course.curriculum) for lesson in module.lessons]
        if lesson_id not in {lesson.id for lesson in lessons}:
            raise ValueError("Unknown lesson for this learning run")
        record = await db.get(LessonProgressRecord, (run.id, user.id, lesson_id))
        if record is None:
            record = LessonProgressRecord(agent_run_id=run.id, user_id=user.id, lesson_id=lesson_id, completed=completed)
            db.add(record)
        else:
            record.completed = completed
        await db.commit()
        completed_lessons = await db.scalar(select(func.count()).select_from(LessonProgressRecord).where(LessonProgressRecord.agent_run_id == run.id, LessonProgressRecord.user_id == user.id, LessonProgressRecord.completed.is_(True)))
        return LearningProgressResponse(run_id=run.id, lesson_id=lesson_id, completed=completed, completed_lessons=completed_lessons or 0, total_lessons=len(lessons))

    @staticmethod
    def evaluate(score_percent: int, confidence: str) -> str:
        if score_percent < 60 or confidence == "low":
            return "Review the prerequisite module and add one guided practice assignment before advancing."
        if score_percent >= 85 and confidence == "high":
            return "Skip the next review block and add an advanced applied project milestone."
        return "Continue with the current sequence and retain the planned practice assignment."


learning_service = LearningService()
