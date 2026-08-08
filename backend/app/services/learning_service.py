import ipaddress
import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import SplitResult, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    LessonWriterAgent, PlannerAgent, ResearchQueryPlannerAgent, ResearchSelectorAgent,
    ResearchSynthesisAgent,
)
from app.browser.gateway import BrowserGateway
from app.core.config import get_settings
from app.core.security import encrypt
from app.harness import AgentHarness
from app.harness.providers.factory import get_runtime
from app.mcp.audit import record_tool_invocation
from app.models.database import (
    AgentRun, AgentSessionRecord, AssignmentSubmissionRecord, LearningRequest,
    LessonProgressRecord, QuizSubmissionRecord, SystemSetting, TranscriptEntryRecord, User,
)
from app.schemas.learning import (
    Assessment, AssignmentSubmissionResponse, Course, CurriculumModule,
    LearningGoal, LearningProgressResponse, LearningRun, LearningRunRequest, Lesson,
    LIVE_AGENT_PROVIDERS, QuizQuestionFeedback, QuizSubmissionResponse, ResearchBrief, Source,
    SourceVisit,
)


class LearningService:
    browser_gateway_factory = BrowserGateway

    async def create_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> LearningRun:
        configured = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
        configured_provider = configured.value if configured else get_settings().agent_provider
        provider = configured_provider if configured_provider in LIVE_AGENT_PROVIDERS else "gemini-cli"
        if provider not in LIVE_AGENT_PROVIDERS:
            raise ValueError("Unsupported agent provider")
        goal = LearningGoal.model_validate(request)
        learning_request = LearningRequest(user_id=user.id, topic=goal.topic, level=goal.level, hours_per_week=goal.hours_per_week, weeks=goal.weeks)
        db.add(learning_request)
        await db.flush()
        run = AgentRun(learning_request_id=learning_request.id, provider=provider)
        db.add(run)
        await db.flush()
        harness = AgentHarness(provider, db)
        planner = PlannerAgent()
        try:
            research_session, research = await self._browser_research(
                db, run.id, provider, goal
            )
            planner_session, planner_output = await harness.start_and_run(
                run.id, planner.name, planner.build_prompt(goal, research.model_dump())
            )
            planner_output, writer_sessions = await self._expand_short_lessons(
                harness, run.id, goal, research, planner_output
            )
            curriculum = self._provider_curriculum(goal, planner_output, research)
            assessment = self._provider_assessment(goal, planner_output)
            result = LearningRun(
                id=run.id, provider=provider, research=research, curriculum=curriculum,
                course=Course(title=f"{goal.topic} learning path", modules=curriculum), assessment=assessment,
                sessions={
                    "Researcher": research_session.id,
                    "Planner": planner_session.id,
                    **writer_sessions,
                },
            )
            result.id = run.id
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return self.public_learning_run(result)
        except Exception:
            run.status, run.completed_at = "failed", datetime.now(timezone.utc)
            await db.commit()
            raise

    async def _expand_short_lessons(
        self,
        harness: AgentHarness,
        run_id: str,
        goal: LearningGoal,
        research: ResearchBrief,
        planner_output: dict,
    ) -> tuple[dict, dict[str, str]]:
        """Use live lesson-writer calls when a planner outline is not yet page-length."""
        expanded_output = json.loads(json.dumps(planner_output))
        curriculum = expanded_output.get("curriculum")
        if not isinstance(curriculum, list):
            return expanded_output, {}
        for module in curriculum:
            if not isinstance(module, dict):
                continue
            if isinstance(module.get("outcomes"), str):
                outcome_text = module["outcomes"].strip()
                outcome_parts = [
                    part.strip(" .")
                    for part in re.split(r"\s*(?:,|;|\band\b)\s*", outcome_text)
                    if len(part.strip(" .")) >= 8
                ]
                module["outcomes"] = outcome_parts if len(outcome_parts) >= 2 else [outcome_text]
            for lesson in module.get("lessons", []):
                if isinstance(lesson, dict) and lesson.get("id") is not None:
                    lesson["id"] = str(lesson["id"])
        writer = LessonWriterAgent()
        sessions: dict[str, str] = {}
        verified_sources = [source.model_dump(mode="json") for source in research.sources]
        for module in curriculum:
            if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
                continue
            for lesson in module["lessons"]:
                if not isinstance(lesson, dict):
                    continue
                paragraphs = lesson.get("paragraphs")
                word_count = sum(
                    len(str(paragraph.get("text") or "").split())
                    for paragraph in paragraphs or []
                    if isinstance(paragraph, dict)
                )
                if word_count >= 1000:
                    continue
                lesson_id = str(lesson.get("id") or "")
                session, output = await harness.start_and_run(
                    run_id,
                    writer.name,
                    writer.build_prompt(
                        goal,
                        {
                            "module": {
                                "week": module.get("week"),
                                "title": module.get("title"),
                                "outcomes": module.get("outcomes"),
                            },
                            "lesson_draft": lesson,
                            "verified_sources": verified_sources,
                        },
                    ),
                )
                expanded = output.get("lesson") if isinstance(output, dict) else None
                if not isinstance(expanded, dict) or str(expanded.get("id")) != lesson_id:
                    raise ValueError(f"LessonWriter must return the requested lesson id {lesson_id}.")
                if not isinstance(expanded.get("paragraphs"), list):
                    raise ValueError(f"LessonWriter must return paragraphs for lesson {lesson_id}.")
                lesson["paragraphs"] = expanded["paragraphs"]
                sessions[f"LessonWriter:{lesson_id}"] = session.id
        return expanded_output, sessions

    async def _browser_research(
        self,
        db: AsyncSession,
        run_id: str,
        provider: str,
        goal: LearningGoal,
    ) -> tuple[AgentSessionRecord, ResearchBrief]:
        """Plan broad discovery, browse public pages, then synthesize verified evidence."""
        gateway = self.browser_gateway_factory()
        audit_session = AgentSessionRecord(
            agent_run_id=run_id,
            agent_name="BrowserResearch",
            provider=provider,
            input_payload={"agent": "Researcher", "pipeline": "browser-research"},
        )
        db.add(audit_session)
        await db.flush()
        started = perf_counter()
        try:
            query_planner = ResearchQueryPlannerAgent()
            query_session, query_output = await self._plain_research_call(
                db,
                run_id,
                provider,
                query_planner.name,
                query_planner.build_prompt(goal),
            )
            queries, replacement_queries, seed_candidates = self._validated_query_plan(
                query_output
            )
            candidates: list[dict[str, str]] = []
            seen_candidates: set[str] = set()

            async def run_search(item: dict[str, str]) -> tuple[dict[str, str], dict, float]:
                call_started = perf_counter()
                result = await gateway.browser_search(item["query"], limit=10)
                result["purpose"] = item["purpose"]
                return item, result, call_started

            search_results = await asyncio.gather(*(run_search(item) for item in queries))
            for _item, result, call_started in search_results:
                await self._audit_browser_call(
                    db, audit_session.id, "browser_search", result, call_started
                )
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
                    candidates.append(
                        {"title": str(item.get("title") or "Public source")[:300], "url": normalized}
                    )
            if len(candidates) < 12:
                replacement_results = await asyncio.gather(
                    *(run_search(item) for item in replacement_queries)
                )
                for _item, result, call_started in replacement_results:
                    await self._audit_browser_call(
                        db, audit_session.id, "browser_search", result, call_started
                    )
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
                        candidates.append(
                            {
                                "title": str(item.get("title") or "Public source")[:300],
                                "url": normalized,
                            }
                        )
            for item in seed_candidates:
                normalized = self._normalize_evidence_url(item["url"])
                if (
                    normalized is None
                    or normalized in seen_candidates
                    or self._is_search_results_url(normalized)
                ):
                    continue
                seen_candidates.add(normalized)
                candidate = {"title": item["title"], "url": normalized, "is_canonical_seed": "true"}
                if kind_hint := item.get("kind_hint") or self._source_kind_hint(item["title"], normalized):
                    candidate["kind_hint"] = kind_hint
                candidates.append(candidate)
            if len(candidates) < 12:
                raise ValueError(
                    "Research discovery remained too narrow after eight parallel queries and two "
                    f"replacement queries; received {len(candidates)} unique public candidates."
                )

            selector = ResearchSelectorAgent()
            # Search pages can be noisy, especially when DuckDuckGo falls back to
            # Bing. Always expose the model-planned canonical candidates first,
            # followed by diverse discovered results. Every chosen URL still has
            # to be opened and verified by the browser before it can be cited.
            candidate_by_url = {item["url"]: item for item in candidates}
            selector_candidates: list[dict[str, str]] = []
            seed_urls: set[str] = set()
            for seed in seed_candidates:
                normalized = self._normalize_evidence_url(seed["url"])
                candidate = candidate_by_url.get(normalized)
                if normalized is None or candidate is None:
                    continue
                seed_urls.add(normalized)
                candidate["is_canonical_seed"] = "true"
                if kind_hint := seed.get("kind_hint") or self._source_kind_hint(seed["title"], normalized):
                    candidate["kind_hint"] = kind_hint
                selector_candidates.append(candidate)
            selector_candidates.extend(
                item for item in candidates if item["url"] not in seed_urls
            )
            selector_session, selector_output = await self._plain_research_call(
                db,
                run_id,
                provider,
                selector.name,
                selector.build_prompt(goal, {"candidates": selector_candidates[:40]}),
            )
            selections = self._validated_research_selections(
                selector_output, selector_candidates[:40]
            )
            selected_urls = [item["url"] for item in selections]
            ordered_urls = selected_urls
            kind_hints = {item["url"]: item["kind"] for item in selections}

            pages: list[dict[str, object]] = []
            seen_pages: set[str] = set()
            visit_ledger: list[SourceVisit] = []

            async def run_read(batch: list[str]) -> tuple[dict, float]:
                call_started = perf_counter()
                result = await gateway.browser_read(batch)
                return result, call_started

            batches = [ordered_urls[offset : offset + 4] for offset in range(0, len(ordered_urls), 4)]
            read_results = await asyncio.gather(*(run_read(batch) for batch in batches))
            for result, call_started in read_results:
                await self._audit_browser_call(
                    db, audit_session.id, "browser_read", result, call_started
                )
                for page in result.get("pages", []):
                    if not isinstance(page, dict):
                        continue
                    requested = self._normalize_evidence_url(page.get("requested_url"))
                    if str(page.get("status", "")).casefold() != "ok":
                        if requested:
                            visit_ledger.append(SourceVisit(url=requested, status="unavailable"))
                        continue
                    normalized = self._normalize_evidence_url(page.get("url"))
                    content = str(page.get("content") or "")[:6000]
                    if normalized is None or normalized in seen_pages or not content.strip():
                        continue
                    seen_pages.add(normalized)
                    title = str(page.get("title") or "Public source")[:500]
                    visit_ledger.append(SourceVisit(url=normalized, title=title, status="read"))
                    pages.append(
                        {
                            "url": normalized,
                            "title": title,
                            "kind_hint": kind_hints.get(normalized),
                            "content": content,
                            "content_is_untrusted": True,
                        }
                    )
            if len(pages) < 8:
                raise ValueError(
                    f"Browser research requires 8 readable public sources; received {len(pages)}."
                )

            synthesis = ResearchSynthesisAgent()
            synthesis_sessions: list[AgentSessionRecord] = []
            synthesized_sources: list[dict] = []
            for index, page_batch in enumerate(
                (pages[offset : offset + 6] for offset in range(0, len(pages), 6)),
                start=1,
            ):
                part_session, part_output = await self._plain_research_call(
                    db,
                    run_id,
                    provider,
                    f"ResearchSynthesisPart{index}",
                    synthesis.build_prompt(goal, {"pages": page_batch}),
                )
                synthesis_sessions.append(part_session)
                synthesized_sources.extend(
                    source for source in part_output.get("sources", [])
                    if isinstance(source, dict)
                )
            synthesis_session = synthesis_sessions[0]
            synthesis_output = {"topic": goal.topic, "sources": synthesized_sources}
            for source in synthesis_output.get("sources", []):
                if not isinstance(source, dict):
                    continue
                normalized = self._normalize_evidence_url(source.get("url"))
                if normalized in kind_hints:
                    source["kind"] = kind_hints[normalized]
            from app.harness import AgentResult

            research = self._verified_research(
                AgentResult(synthesis_output, visited_urls=frozenset(seen_pages))
            )
            selected = {source.url for source in research.sources}
            research = research.model_copy(
                update={
                    "visited_sources": [
                        visit.model_copy(update={"selected": visit.url in selected})
                        for visit in visit_ledger
                    ]
                }
            )
            audit_session.status = "completed"
            audit_session.output_payload = {
                "candidate_count": len(candidates),
                "selected_count": len(selections),
                "read_count": len(pages),
                "query_planner_session_id": query_session.id,
                "selector_session_id": selector_session.id,
                "synthesis_session_ids": [session.id for session in synthesis_sessions],
            }
            self._add_transcript_entry(
                db,
                audit_session.id,
                "system",
                f"Completed {len(queries)} parallel research queries, selected 12 candidates, and read {len(pages)} public pages. Page bodies are not persisted.",
                1,
            )
            return synthesis_session, research
        except Exception:
            audit_session.status = "failed"
            audit_session.error_message = "Browser research pipeline failed."
            raise
        finally:
            audit_session.completed_at = datetime.now(timezone.utc)
            audit_session.duration_ms = int((perf_counter() - started) * 1000)
            await db.flush()

    async def _plain_research_call(
        self,
        db: AsyncSession,
        run_id: str,
        provider: str,
        role: str,
        prompt: str,
    ) -> tuple[AgentSessionRecord, dict]:
        """Call a non-MCP role without persisting browser page bodies in transcripts."""
        session = AgentSessionRecord(
            agent_run_id=run_id,
            agent_name=role,
            provider=provider,
            input_payload={"agent": role, "pipeline": "browser-research"},
        )
        db.add(session)
        await db.flush()
        started = perf_counter()
        try:
            redacted_inputs = {
                "ResearchQueryPlanner": (
                    "Planned eight complementary research queries, two bounded replacements, "
                    "and browser-verifiable canonical seed URLs."
                ),
                "ResearchSelector": "Selected public source candidates from normalized URLs.",
            }
            redacted_input = redacted_inputs.get(role)
            if redacted_input is None and role.startswith("ResearchSynthesisPart"):
                redacted_input = (
                    "Synthesized one bounded batch of browser-read evidence. Page bodies were supplied "
                    "in memory and are intentionally omitted from the durable transcript."
                )
            redacted_input = redacted_input or "Processed bounded research evidence."
            self._add_transcript_entry(db, session.id, "user", redacted_input, 1)
            execution = await get_runtime(provider, role).execute(prompt)
            payload = execution.payload if hasattr(execution, "payload") else execution
            if not isinstance(payload, dict):
                raise ValueError(f"{role} must return a JSON object.")  # noqa: TRY004
            session.output_payload = payload
            session.status = "completed"
            self._add_transcript_entry(db, session.id, "assistant", json.dumps(payload), 2)
            return session, payload
        except Exception as error:
            session.status = "failed"
            session.error_message = str(error)[:2000]
            raise
        finally:
            session.completed_at = datetime.now(timezone.utc)
            session.duration_ms = int((perf_counter() - started) * 1000)
            await db.flush()

    @classmethod
    def _validated_query_plan(
        cls,
        output: dict,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        if not isinstance(output, dict):
            raise ValueError("ResearchQueryPlanner must return a JSON object.")  # noqa: TRY004

        def validate_queries(key: str, expected: int) -> list[dict[str, str]]:
            items = output.get(key)
            if not isinstance(items, list) or len(items) != expected:
                raise ValueError(
                    f"ResearchQueryPlanner must return exactly {expected} {key}."
                )
            validated: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("ResearchQueryPlanner returned an invalid query item.")  # noqa: TRY004
                query = " ".join(str(item.get("query") or "").split())
                purpose = " ".join(str(item.get("purpose") or "").split())
                normalized = query.casefold()
                if (
                    not 8 <= len(query) <= 300
                    or not 8 <= len(purpose) <= 300
                    or normalized in seen
                ):
                    raise ValueError("ResearchQueryPlanner queries must be unique and specific.")
                seen.add(normalized)
                validated.append({"query": query, "purpose": purpose})
            return validated

        queries = validate_queries("queries", 8)
        replacement_queries = validate_queries("replacement_queries", 2)
        all_queries = {item["query"].casefold() for item in queries}
        if any(item["query"].casefold() in all_queries for item in replacement_queries):
            raise ValueError("ResearchQueryPlanner replacement queries must be distinct.")

        raw_seeds = output.get("seed_candidates")
        if not isinstance(raw_seeds, list) or not 8 <= len(raw_seeds) <= 12:
            raise ValueError("ResearchQueryPlanner must propose 8-12 canonical seed candidates.")
        seeds: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in raw_seeds:
            if not isinstance(item, dict):
                continue
            normalized = cls._normalize_evidence_url(item.get("url"))
            title = " ".join(str(item.get("title") or "Public source").split())[:300]
            purpose = " ".join(str(item.get("purpose") or "Candidate evidence").split())[:500]
            if (
                normalized is None
                or normalized in seen_urls
                or cls._is_search_results_url(normalized)
                or len(purpose) < 8
            ):
                continue
            seen_urls.add(normalized)
            declared_kind = item.get("kind")
            kind_hint = declared_kind if declared_kind in {
                "documentation", "paper", "book", "lecture", "slides", "article", "repository"
            } else cls._source_kind_hint(title, normalized)
            seed = {"title": title, "url": normalized, "purpose": purpose}
            if kind_hint:
                seed["kind_hint"] = kind_hint
            seeds.append(seed)
        if len(seeds) < 8:
            raise ValueError("ResearchQueryPlanner must provide at least 8 valid HTTPS seed URLs.")
        return queries, replacement_queries, seeds

    @classmethod
    def _validated_research_selections(
        cls,
        output: dict,
        candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        selections = output.get("selections") if isinstance(output, dict) else None
        if not isinstance(selections, list) or len(selections) != 12:
            raise ValueError("ResearchSelector must choose exactly 12 candidates.")
        candidate_by_url = {item["url"]: item for item in candidates}
        allowed_urls = set(candidate_by_url)
        allowed_kinds = {"documentation", "paper", "book", "lecture", "slides", "article", "repository"}
        validated: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in selections:
            if not isinstance(item, dict):
                continue
            normalized = cls._normalize_evidence_url(item.get("url") or item.get("requested_url"))
            kind = candidate_by_url.get(normalized, {}).get("kind_hint") or item.get("kind")
            if normalized not in allowed_urls or normalized in seen or kind not in allowed_kinds:
                continue
            seen.add(normalized)
            validated.append({"url": normalized, "kind": kind})
        for candidate in candidates:
            if len(validated) == 12:
                break
            normalized = candidate["url"]
            if normalized in seen:
                continue
            kind = candidate.get("kind_hint") or cls._source_kind_hint(
                candidate.get("title", ""), normalized
            ) or "article"
            seen.add(normalized)
            validated.append({"url": normalized, "kind": kind})
        if len(validated) != 12:
            raise ValueError("ResearchSelector did not yield 12 unique valid candidates.")
        return cls._ensure_source_mix(validated, candidates)

    @classmethod
    def _ensure_source_mix(
        cls,
        selections: list[dict[str, str]],
        candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Repair only source-type omissions using canonical typed candidates."""
        repaired = list(selections)
        selected_urls = {item["url"] for item in repaired}
        requirements = [
            {"paper", "book"}, {"documentation", "repository"}, {"article"},
        ]
        for required in requirements:
            if any(item["kind"] in required for item in repaired):
                continue
            replacement = next(
                (
                    {"url": item["url"], "kind": item["kind_hint"]}
                    for item in candidates
                    if item.get("kind_hint") in required and item["url"] not in selected_urls
                ),
                None,
            )
            if replacement is None:
                label = " or ".join(sorted(required))
                raise ValueError(f"ResearchSelector source mix is incomplete; missing: {label}")
            counts = Counter(item["kind"] for item in repaired)
            replace_at = next(
                (
                    index for index in range(len(repaired) - 1, -1, -1)
                    if counts[repaired[index]["kind"]] > 1
                ),
                None,
            )
            if replace_at is None:
                raise ValueError("ResearchSelector source mix could not be balanced.")
            selected_urls.remove(repaired[replace_at]["url"])
            repaired[replace_at] = replacement
            selected_urls.add(replacement["url"])
        return repaired

    @staticmethod
    def _source_kind_hint(title: str, url: str) -> str | None:
        """Infer only high-confidence source types; leave ambiguous pages to Gemini."""
        text = f"{title} {url}".casefold()
        host = urlsplit(url).hostname or ""
        if host == "arxiv.org" or "doi.org/" in text or " paper" in text:
            return "paper"
        if host == "github.com" or " repository" in text:
            return "repository"
        if "documentation" in text or "/docs/" in text or "readthedocs" in host:
            return "documentation"
        if any(marker in text for marker in ("book", "chapter", "textbook")):
            return "book"
        if "slides" in text or "slide deck" in text:
            return "slides"
        if "lecture" in text:
            return "lecture"
        return None

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
        await record_tool_invocation(
            db,
            session_id,
            tool_name,
            status,
            {
                "query": str(result.get("query") or "")[:500] if tool_name == "browser_search" else None,
                "purpose": str(result.get("purpose") or "")[:500] if tool_name == "browser_search" else None,
                "urls": urls[:20],
                "domains": domains[:20],
                "result_count": len(items),
                "success_count": success_count,
                "page_results": page_results,
                "pipeline": "browser-research",
            },
            str(error_payload.get("code") or "Browser operation unavailable") if status == "failed" else None,
            started_at=started_at,
        )

    @classmethod
    def _verified_research(cls, research_output: dict) -> ResearchBrief:
        """Keep only unique citations backed by a successful browser_read result."""
        research = ResearchBrief.model_validate(research_output)
        visited_urls = {
            normalized
            for url in getattr(research_output, "visited_urls", ())
            if (normalized := cls._normalize_evidence_url(url)) is not None
        }
        verified: list[Source] = []
        seen: set[str] = set()
        for source in research.sources:
            normalized = cls._normalize_evidence_url(source.url)
            if (
                normalized is None
                or normalized not in visited_urls
                or normalized in seen
                or cls._is_search_results_url(normalized)
            ):
                continue
            seen.add(normalized)
            key_points = [point.strip() for point in source.key_points if point.strip()]
            if len(key_points) < 2 or any(len(point) < 20 for point in key_points):
                continue
            verified.append(source.model_copy(update={"url": normalized, "key_points": key_points}))
            if len(verified) == 12:
                break
        if len(verified) < 8:
            raise ValueError(
                "Research requires at least 8 unique browser-verified sources; "
                f"received {len(verified)}. Run browser_read on every source before citing it."
            )
        kinds = {source.kind for source in verified}
        source_groups = [
            ({"paper", "book"}, "a paper or book"),
            ({"documentation", "repository"}, "documentation or a repository"),
            ({"article"}, "an explanatory article"),
        ]
        missing_groups = [label for group, label in source_groups if not kinds.intersection(group)]
        if missing_groups:
            raise ValueError(
                "Research must include primary, practical, and explanatory evidence; "
                f"missing: {', '.join(missing_groups)}."
            )
        selected = {source.url for source in verified}
        discovered: list[str] = []
        unavailable: list[str] = []
        for event in getattr(research_output, "tool_events", ()):
            metadata = event.metadata if isinstance(event.metadata, dict) else {}
            if "browser_search" in event.tool_name:
                for url in metadata.get("urls", []):
                    normalized = cls._normalize_evidence_url(url)
                    if normalized and normalized not in discovered:
                        discovered.append(normalized)
            if "browser_read" in event.tool_name:
                for page in metadata.get("page_results", []):
                    if not isinstance(page, dict) or page.get("status") != "unavailable":
                        continue
                    normalized = cls._normalize_evidence_url(page.get("url"))
                    if normalized and normalized not in unavailable:
                        unavailable.append(normalized)
        ledger = [
            SourceVisit(url=url, status="read", selected=url in selected)
            for url in sorted(visited_urls)
        ]
        read_urls = {entry.url for entry in ledger}
        ledger.extend(
            SourceVisit(url=url, status="discovered", selected=False)
            for url in discovered
            if url not in read_urls and url not in unavailable
        )
        ledger.extend(
            SourceVisit(url=url, status="unavailable", selected=False)
            for url in unavailable
            if url not in read_urls
        )
        return research.model_copy(update={"sources": verified, "visited_sources": ledger})

    @classmethod
    def _provider_curriculum(
        cls,
        goal: LearningGoal,
        planner_output: dict,
        research: ResearchBrief,
    ) -> list[CurriculumModule]:
        """Validate complete provider-authored lessons and their evidence links."""
        payload = planner_output.get("curriculum") if isinstance(planner_output, dict) else None
        if not isinstance(payload, list):
            raise ValueError("Planner must return a curriculum array.")  # noqa: TRY004
        try:
            modules = [CurriculumModule.model_validate(item) for item in payload]
        except (TypeError, ValueError) as error:
            raise ValueError("Planner returned an invalid curriculum structure.") from error

        expected_weeks = set(range(1, goal.weeks + 1))
        actual_weeks = [module.week for module in modules]
        if len(actual_weeks) != goal.weeks or set(actual_weeks) != expected_weeks:
            raise ValueError(
                f"Planner must return exactly one module for each week 1 through {goal.weeks}."
            )

        verified_sources = {source.url: source for source in research.sources}
        verified_urls = set(verified_sources)
        seen_lesson_ids: set[str] = set()
        grounded: list[CurriculumModule] = []
        for module in sorted(modules, key=lambda item: item.week):
            cls._validate_module_content(module, goal)
            module_urls = cls._grounded_source_urls(
                module.source_urls, verified_urls, f"module week {module.week}"
            )
            if not any(
                verified_sources[url].kind in {"documentation", "paper", "book"}
                for url in module_urls
            ):
                raise ValueError(
                    f"Planner module week {module.week} must cite a verified primary source."
                )
            if len(module.lessons) < 2:
                raise ValueError(
                    f"Planner module week {module.week} must contain at least two complete lessons."
                )
            lessons: list[Lesson] = []
            for lesson in module.lessons:
                if lesson.id in seen_lesson_ids:
                    raise ValueError(f"Planner lesson id must be unique: {lesson.id}")
                seen_lesson_ids.add(lesson.id)
                cls._validate_lesson_content(lesson, module.week)
                paragraphs = []
                paragraph_urls: list[str] = []
                for index, paragraph in enumerate(lesson.paragraphs, start=1):
                    urls = cls._grounded_source_urls(
                        paragraph.source_urls,
                        verified_urls,
                        f"lesson {lesson.id} paragraph {index}",
                    )
                    for url in urls:
                        if url not in paragraph_urls:
                            paragraph_urls.append(url)
                    paragraphs.append(paragraph.model_copy(update={"source_urls": urls}))
                if len(paragraph_urls) < 2:
                    raise ValueError(
                        f"Planner lesson {lesson.id} must synthesize at least two verified sources."
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
                            "source_urls": lesson_urls,
                        }
                    )
                )
            if sum(lesson.estimated_minutes for lesson in lessons) > goal.hours_per_week * 60:
                raise ValueError(
                    f"Planner module week {module.week} lesson time exceeds the learner's weekly-hour budget."
                )
            grounded.append(
                module.model_copy(update={"source_urls": module_urls, "lessons": lessons})
            )
        return grounded

    @staticmethod
    def _provider_assessment(goal: LearningGoal, planner_output: dict) -> Assessment:
        """Validate provider-authored quizzes and practical work without synthetic padding."""
        payload = planner_output.get("assessment") if isinstance(planner_output, dict) else None
        if not isinstance(payload, dict):
            raise ValueError("Planner must return an assessment object.")  # noqa: TRY004
        payload = json.loads(json.dumps(payload))
        assignment = payload.get("assignment")
        if isinstance(assignment, dict) and isinstance(assignment.get("rubric"), dict):
            assignment["rubric"] = [
                f"{label}: {criterion}" for label, criterion in assignment["rubric"].items()
            ]
        if isinstance(payload.get("project"), dict):
            project = payload["project"]
            payload["project"] = ". ".join(
                str(value).strip().rstrip(".")
                for value in project.values()
                if isinstance(value, str) and value.strip()
            ) + "."
        try:
            assessment = Assessment.model_validate(payload)
        except (TypeError, ValueError) as error:
            raise ValueError("Planner returned an invalid assessment structure.") from error

        questions = assessment.quiz_items or assessment.quiz
        minimum_questions = goal.weeks * 2
        maximum_questions = goal.weeks * 5
        if not minimum_questions <= len(questions) <= maximum_questions:
            raise ValueError(
                f"Planner must return 2-5 quiz questions per week ({minimum_questions}-{maximum_questions} total)."
            )

        expected_weeks = set(range(1, goal.weeks + 1))
        questions_per_week = Counter(question.module_week for question in questions)
        if set(questions_per_week) != expected_weeks or any(
            not 2 <= questions_per_week[week] <= 5 for week in expected_weeks
        ):
            raise ValueError("Planner must return 2-5 quiz questions for every requested week.")

        seen_ids: set[str] = set()
        for question in questions:
            choices = [choice.strip() for choice in question.choices]
            if not question.id.strip() or question.id in seen_ids:
                raise ValueError("Planner quiz question ids must be non-empty and unique.")
            seen_ids.add(question.id)
            if len(question.prompt.strip()) < 20:
                raise ValueError(f"Planner quiz question {question.id} needs a complete prompt.")
            if len(set(choices)) != len(choices) or any(len(choice) < 2 for choice in choices):
                raise ValueError(f"Planner quiz question {question.id} needs distinct, complete choices.")
            if question.correct_answer not in question.choices:
                raise ValueError(
                    f"Planner quiz question {question.id} must include correct_answer in choices."
                )
            if not question.explanation or len(question.explanation.strip()) < 20:
                raise ValueError(
                    f"Planner quiz question {question.id} needs a substantive answer explanation."
                )

        if any(len(item.strip()) < 10 for item in assessment.assignment.deliverables):
            raise ValueError("Planner assignment deliverables must be concrete.")
        if any(len(item.strip()) < 10 for item in assessment.assignment.rubric):
            raise ValueError("Planner assignment rubric criteria must be observable.")

        return assessment.model_copy(update={"quiz": questions, "quiz_items": questions})

    @staticmethod
    def _validate_module_content(module: CurriculumModule, goal: LearningGoal) -> None:
        if len(module.title.strip()) < 3 or len(module.overview.strip()) < 40:
            raise ValueError(f"Planner module week {module.week} needs a complete title and overview.")
        if len(module.outcomes) < 2 or any(len(outcome.strip()) < 10 for outcome in module.outcomes):
            raise ValueError(f"Planner module week {module.week} needs at least two concrete outcomes.")
        if module.estimated_hours > goal.hours_per_week:
            raise ValueError(
                f"Planner module week {module.week} exceeds the learner's weekly-hour budget."
            )

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
    def _validate_lesson_content(lesson: Lesson, week: int) -> None:
        fields = {
            "title": (lesson.title, 3),
            "objective": (lesson.objective, 12),
            "practice": (lesson.practice, 20),
        }
        for name, (value, minimum) in fields.items():
            if not isinstance(value, str) or len(value.strip()) < minimum:
                raise ValueError(
                    f"Planner lesson {lesson.id or '<unknown>'} in week {week} needs complete {name}."
                )
        if not 4 <= len(lesson.paragraphs) <= 7:
            raise ValueError(
                f"Planner lesson {lesson.id or '<unknown>'} in week {week} must contain 4-7 cited paragraphs."
            )
        texts = [paragraph.text.strip() for paragraph in lesson.paragraphs]
        word_count = sum(len(text.split()) for text in texts)
        if not 1000 <= word_count <= 1800:
            raise ValueError(
                f"Planner lesson {lesson.id or '<unknown>'} in week {week} must contain 1000-1800 substantive words."
            )
        normalized = [re.sub(r"\s+", " ", text.casefold()) for text in texts]
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"Planner lesson {lesson.id} repeats a paragraph.")
        all_sentences: list[str] = []
        for text in texts:
            sentences = [
                re.sub(r"\s+", " ", sentence.strip().casefold())
                for sentence in re.split(r"(?<=[.!?])\s+", text)
                if len(sentence.split()) >= 5
            ]
            if len(sentences) >= 3 and len(set(sentences)) / len(sentences) < 0.75:
                raise ValueError(f"Planner lesson {lesson.id} repeats sentences instead of teaching the topic.")
            all_sentences.extend(sentences)
        if any(count > 2 for count in Counter(all_sentences).values()):
            raise ValueError(f"Planner lesson {lesson.id} repeats sentences across paragraphs.")

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
        if not run.result:
            raise ValueError("Learning run has not completed")
        return LearningRun.model_validate(run.result)

    @staticmethod
    def public_learning_run(run: LearningRun) -> LearningRun:
        """Never reveal answer keys before a learner has submitted the quiz."""
        quiz_items = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz_items]
        legacy_quiz = [item.model_copy(update={"correct_answer": None, "explanation": None}) for item in run.assessment.quiz]
        assessment = run.assessment.model_copy(update={"quiz_items": quiz_items, "quiz": legacy_quiz})
        return run.model_copy(update={"assessment": assessment})

    async def submit_quiz(self, db: AsyncSession, user: User, run: AgentRun, answers: list[tuple[str, str]]) -> QuizSubmissionResponse:
        course = self.learning_run(run)
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
