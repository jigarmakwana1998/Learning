import ipaddress
import json
import re
from collections import Counter
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import SplitResult, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    ExaminerAgent, PlannerAgent, ResearcherAgent, ResearchSelectorAgent,
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
    Assessment, Assignment, AssignmentSubmissionResponse, Course, CurriculumModule,
    LearningGoal, LearningProgressResponse, LearningRun, LearningRunRequest, Lesson,
    QuizQuestionFeedback, QuizSubmissionResponse, ResearchBrief, Source, SourceVisit,
)


class LearningService:
    browser_gateway_factory = BrowserGateway

    async def create_run(self, db: AsyncSession, user: User, request: LearningRunRequest) -> LearningRun:
        configured = await db.scalar(select(SystemSetting).where(SystemSetting.key == "agent_provider"))
        provider = configured.value if configured else get_settings().agent_provider
        if provider not in {"mock", "codex", "gemini-cli", "antigravity-cli"}:
            raise ValueError("Unsupported agent provider")
        goal = LearningGoal.model_validate(request)
        learning_request = LearningRequest(user_id=user.id, topic=goal.topic, level=goal.level, hours_per_week=goal.hours_per_week, weeks=goal.weeks)
        db.add(learning_request)
        await db.flush()
        run = AgentRun(learning_request_id=learning_request.id, provider=provider)
        db.add(run)
        await db.flush()
        harness = AgentHarness(provider, db)
        researcher, planner, examiner = ResearcherAgent(), PlannerAgent(), ExaminerAgent()
        try:
            if provider == "mock":
                research_session, _ = await harness.start_and_run(run.id, researcher.name, researcher.build_prompt(goal))
                planner_session, _ = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, {"research": "local deterministic course"}))
                examiner_session, _ = await harness.start_and_run(run.id, examiner.name, examiner.build_prompt(goal, {"curriculum": "local deterministic course"}))
                result = self._mock_run(goal, provider, {"Researcher": research_session.id, "Planner": planner_session.id, "Examiner": examiner_session.id})
            else:
                research_session, research = await self._research_with_fallback(
                    db, harness, run.id, provider, goal, researcher
                )
                planner_session, planner_output = await harness.start_and_run(run.id, planner.name, planner.build_prompt(goal, research.model_dump()))
                curriculum = self._provider_curriculum(goal, planner_output, research)
                # Keep the current deterministic assessment as a compatibility
                # placeholder. Course content is complete at this point, so do not
                # spend quota or make success depend on another provider call.
                assessment = self._build_assessment(goal)
                result = LearningRun(
                    id=run.id, provider=provider, research=research, curriculum=curriculum,
                    course=Course(title=f"{goal.topic} learning path", modules=curriculum), assessment=assessment,
                    sessions={"Researcher": research_session.id, "Planner": planner_session.id},
                )
            result.id = run.id
            run.status, run.result, run.completed_at = "completed", result.model_dump(mode="json"), datetime.now(timezone.utc)
            await db.commit()
            return self.public_learning_run(result)
        except Exception:
            run.status, run.completed_at = "failed", datetime.now(timezone.utc)
            await db.commit()
            raise

    async def _research_with_fallback(
        self,
        db: AsyncSession,
        harness: AgentHarness,
        run_id: str,
        provider: str,
        goal: LearningGoal,
        researcher: ResearcherAgent,
    ) -> tuple[AgentSessionRecord, ResearchBrief]:
        """Use MCP research first and recover only from Gemini terminal errors."""
        try:
            session, output = await harness.start_and_run(
                run_id, researcher.name, researcher.build_prompt(goal)
            )
        except RuntimeError as error:
            if provider != "gemini-cli" or not self._is_fallback_research_error(error):
                raise
            return await self._fallback_research(db, run_id, provider, goal)
        return session, self._verified_research(output)

    @staticmethod
    def _is_fallback_research_error(error: RuntimeError) -> bool:
        message = str(error).casefold()
        if "rate limit exceeded" in message:
            return False
        return (
            "returned a provider error" in message
            or "must emit the configured json response format" in message
            or "timed out" in message
        )

    async def _fallback_research(
        self,
        db: AsyncSession,
        run_id: str,
        provider: str,
        goal: LearningGoal,
    ) -> tuple[AgentSessionRecord, ResearchBrief]:
        """Bounded deep-browser recovery with two plain model decisions."""
        gateway = self.browser_gateway_factory()
        audit_session = AgentSessionRecord(
            agent_run_id=run_id,
            agent_name="ResearchFallbackBrowser",
            provider=provider,
            input_payload={"agent": "Researcher", "fallback": "direct-browser"},
        )
        db.add(audit_session)
        await db.flush()
        started = perf_counter()
        try:
            candidates: list[dict[str, str]] = []
            seen_candidates: set[str] = set()
            queries = (
                f"{goal.topic} original research paper foundational definition",
                f"{goal.topic} official documentation implementation architecture",
                f"{goal.topic} textbook chapter university lecture slides pdf",
                f"{goal.topic} high quality technical blog worked example limitations",
            )
            for query in queries:
                call_started = perf_counter()
                result = await gateway.browser_search(query, limit=10)
                await self._audit_fallback_browser_call(
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
                raise ValueError(
                    f"Browser research requires at least 12 public candidates; received {len(candidates)}."
                )

            selector = ResearchSelectorAgent()
            selector_session, selector_output = await self._plain_fallback_call(
                db,
                run_id,
                provider,
                selector.name,
                selector.build_prompt(goal, {"candidates": candidates[:32]}),
            )
            selections = self._validated_fallback_selections(selector_output, candidates)
            selected_urls = [item["url"] for item in selections]
            ordered_urls = selected_urls
            kind_hints = {item["url"]: item["kind"] for item in selections}

            pages: list[dict[str, object]] = []
            seen_pages: set[str] = set()
            visit_ledger: list[SourceVisit] = []
            for offset in range(0, len(ordered_urls), 4):
                batch = ordered_urls[offset : offset + 4]
                call_started = perf_counter()
                result = await gateway.browser_read(batch)
                await self._audit_fallback_browser_call(
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
                    f"Browser fallback requires 8 readable public sources; received {len(pages)}."
                )

            synthesis = ResearchSynthesisAgent()
            synthesis_session, synthesis_output = await self._plain_fallback_call(
                db,
                run_id,
                provider,
                synthesis.name,
                synthesis.build_prompt(goal, {"pages": pages}),
            )
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
                "selector_session_id": selector_session.id,
                "synthesis_session_id": synthesis_session.id,
            }
            self._add_transcript_entry(
                db,
                audit_session.id,
                "system",
                f"Completed four focused searches, selected 12 candidates, and read {len(pages)} public pages. Page bodies are not persisted.",
                1,
            )
            return synthesis_session, research
        except Exception:
            audit_session.status = "failed"
            audit_session.error_message = "Direct browser research fallback failed."
            raise
        finally:
            audit_session.completed_at = datetime.now(timezone.utc)
            audit_session.duration_ms = int((perf_counter() - started) * 1000)
            await db.flush()

    async def _plain_fallback_call(
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
            input_payload={"agent": role, "fallback": True},
        )
        db.add(session)
        await db.flush()
        started = perf_counter()
        try:
            redacted_input = (
                "Selected public source candidates from normalized URLs."
                if role == "ResearchSelector"
                else "Synthesized browser-read evidence. Page bodies were supplied in memory and are intentionally omitted from the durable transcript."
            )
            self._add_transcript_entry(db, session.id, "user", redacted_input, 1)
            execution = await get_runtime(provider, role).execute(prompt)
            payload = execution.payload if hasattr(execution, "payload") else execution
            if not isinstance(payload, dict):
                raise ValueError(f"{role} must return a JSON object.")
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
    def _validated_fallback_selections(
        cls,
        output: dict,
        candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        selections = output.get("selections") if isinstance(output, dict) else None
        if not isinstance(selections, list) or len(selections) != 12:
            raise ValueError("ResearchSelector must choose exactly 12 candidates.")
        allowed_urls = {item["url"] for item in candidates}
        allowed_kinds = {"documentation", "paper", "book", "lecture", "slides", "article", "repository"}
        validated: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in selections:
            if not isinstance(item, dict):
                raise ValueError("ResearchSelector returned an invalid selection.")
            normalized = cls._normalize_evidence_url(item.get("url") or item.get("requested_url"))
            kind = item.get("kind")
            if normalized not in allowed_urls or normalized in seen or kind not in allowed_kinds:
                raise ValueError("ResearchSelector must use unique candidate URLs and supported kinds.")
            seen.add(normalized)
            validated.append({"url": normalized, "kind": kind})
        kinds = {item["kind"] for item in validated}
        required = {"documentation", "paper", "book", "article", "repository"}
        if missing := required - kinds:
            raise ValueError(
                "ResearchSelector source mix is incomplete; missing: " + ", ".join(sorted(missing))
            )
        if not kinds.intersection({"lecture", "slides"}):
            raise ValueError("ResearchSelector source mix must include a lecture or slide deck.")
        return validated

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
    async def _audit_fallback_browser_call(
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
                "urls": urls[:20],
                "domains": domains[:20],
                "result_count": len(items),
                "success_count": success_count,
                "page_results": page_results,
                "fallback": True,
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
        required_kinds = {"documentation", "paper", "book", "article", "repository"}
        missing_kinds = required_kinds - kinds
        if missing_kinds:
            raise ValueError(
                "Research must cover documentation, paper, book, article, and repository sources; "
                f"missing: {', '.join(sorted(missing_kinds))}."
            )
        if not kinds.intersection({"lecture", "slides"}):
            raise ValueError("Research must include a browser-verified lecture or slide deck.")
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
            raise ValueError("Planner must return a curriculum array.")
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
        if not 1200 <= word_count <= 1800:
            raise ValueError(
                f"Planner lesson {lesson.id or '<unknown>'} in week {week} must contain 1200-1800 substantive words."
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

    def _mock_run(self, goal: LearningGoal, provider: str, sessions: dict[str, str]) -> LearningRun:
        curriculum = self._enrich_curriculum(goal, [
            CurriculumModule(
                week=week,
                title=self._module_title(goal.topic, week),
                outcomes=self._outcomes(goal.topic, goal.level, week),
                source_urls=[],
            )
            for week in range(1, goal.weeks + 1)
        ])
        assessment = self._build_assessment(goal)
        return LearningRun(
            id="", provider=provider, research=ResearchBrief(topic=goal.topic, sources=[]),
            curriculum=curriculum, course=Course(title=f"{goal.topic} learning path", modules=curriculum),
            assessment=assessment, sessions=sessions,
        )

    @staticmethod
    def _module_title(topic: str, week: int) -> str:
        phases = ["Foundations and vocabulary", "Core workflow", "Guided practice", "Integration and reflection"]
        return f"{topic}: {phases[min(week - 1, len(phases) - 1)]}"

    @staticmethod
    def _outcomes(topic: str, level: str, week: int) -> list[str]:
        if week == 1:
            return [f"Explain the essential vocabulary of {topic}", f"Set up a repeatable {topic} study and practice environment"]
        if week == 2:
            return [f"Apply a core {topic} workflow to a small example", "Check work against documentation and expected outcomes"]
        return [f"Complete and explain a {level}-level {topic} practice task", "Identify one improvement after reviewing evidence from the task"]

    def _enrich_curriculum(self, goal: LearningGoal, curriculum: list[CurriculumModule]) -> list[CurriculumModule]:
        """Make every generated outline usable in the study player, including CLI-agent output."""
        enriched: list[CurriculumModule] = []
        for module in curriculum:
            week = module.week
            lessons = module.lessons or [
                Lesson(
                    id=f"week-{week}-learn",
                    title=f"Learn: {module.title}",
                    objective=module.outcomes[0] if module.outcomes else f"Build a working mental model of {goal.topic}",
                    content=(
                        f"### Focus\nThis lesson turns **{goal.topic}** into a concrete workflow. Read one primary source, "
                        "write down unfamiliar terms, and connect each term to an example.\n\n"
                        "### Study loop\n1. Read a short reference section.\n2. Reproduce its smallest example.\n"
                        "3. Change one input and record what changed.\n4. Explain the result in your own words.\n\n"
                        "### Checkpoint\nYou should be able to state the problem this technique solves, its inputs, and how to verify its output."
                    ),
                    practice=f"Create a one-page {goal.topic} note with three terms, one tiny example, and one question to investigate.",
                    estimated_minutes=max(20, min(90, goal.hours_per_week * 12)),
                    source_urls=module.source_urls,
                ),
                Lesson(
                    id=f"week-{week}-apply",
                    title=f"Apply: {module.title}",
                    objective=module.outcomes[-1] if module.outcomes else f"Practise {goal.topic} with evidence",
                    content=(
                        f"### Deliberate practice\nChoose one small, observable use of **{goal.topic}**. Work in short iterations: "
                        "predict the result, try it, compare the result with your prediction, and capture the evidence.\n\n"
                        "### Reflection\nDescribe one mistake or surprise. Then revise the example once, explaining why the revision is stronger."
                    ),
                    practice=f"Complete a 30-minute {goal.topic} exercise and save the starting point, final result, and a short reflection.",
                    estimated_minutes=max(20, min(90, goal.hours_per_week * 12)),
                    source_urls=module.source_urls,
                ),
            ]
            enriched.append(module.model_copy(update={
                "overview": module.overview or f"Week {week} combines focused study and hands-on {goal.topic} practice.",
                "estimated_hours": module.estimated_hours or max(1, goal.hours_per_week),
                "lessons": lessons,
            }))
        return enriched

    def _build_assessment(self, goal: LearningGoal) -> Assessment:
        questions = []
        for week in range(1, goal.weeks + 1):
            questions.extend([
                {
                    "id": f"week-{week}-q1", "module_week": week,
                    "prompt": f"When beginning a new {goal.topic} task, what is the most reliable first step?",
                    "choices": ["Define the goal, key terms, and a small observable example", "Start with the largest possible project", "Memorize every reference page", "Skip validation until the end"],
                    "correct_answer": "Define the goal, key terms, and a small observable example",
                    "explanation": "A small observable example creates a feedback loop and makes the topic manageable.",
                },
                {
                    "id": f"week-{week}-q2", "module_week": week,
                    "prompt": f"How should you check a {goal.topic} practice result?",
                    "choices": ["Compare it with a documented expectation and explain any difference", "Assume it is right if it looks plausible", "Only ask someone else to verify it", "Change several variables at once"],
                    "correct_answer": "Compare it with a documented expectation and explain any difference",
                    "explanation": "Comparing one result to a known expectation turns practice into evidence-based learning.",
                },
            ])
        quiz_items = [self._quiz_item(item) for item in questions]
        assignment = Assignment(
            title=f"{goal.topic} evidence notebook",
            prompt=f"Build a small {goal.topic} example that demonstrates one course outcome. Include your initial prediction, the steps you followed, evidence of the result, and a reflection.",
            deliverables=["A reproducible example or walkthrough", "A short explanation of the concepts used", "Evidence of the result", "A reflection describing one revision"],
            rubric=["The example has a clear goal and scope", "Concepts are explained accurately", "Evidence supports the claimed result", "Reflection identifies a useful next step"],
        )
        return Assessment(quiz=quiz_items, quiz_items=quiz_items, assignment=assignment, project=f"Complete a portfolio-ready {goal.topic} project by week {goal.weeks}, documenting decisions and validation evidence.")

    @staticmethod
    def _quiz_item(payload: dict):
        from app.schemas.learning import QuizItem
        return QuizItem(**payload)

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
            raise ValueError(f"Unknown quiz question: {sorted(unknown)[0]}")
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
