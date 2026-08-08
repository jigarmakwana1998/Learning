"""Bounded browser research facade exposed to an LLM through MCP."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlencode

from app.core.config import get_settings

from .client import AgentBrowserClient, AgentBrowserError, output_text
from .policy import UrlPolicyError, hostname_for_url, validate_public_https_url

MAX_URLS_PER_READ = 4
MAX_PAGE_CHARACTERS = 6000

_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,300})\]\((https?://[^\s)]+)\)")
_SNAPSHOT_LINK = re.compile(
    r"(?:link\s+[\"'](?P<title>[^\"']+)[\"'].*?(?:url|href)[=:]\s*[\"']?|(?:url|href)[=:]\s*[\"']?)"
    r"(?P<url>https?://[^\s\"'\]]+)",
    re.IGNORECASE,
)
_RSS_ITEM = re.compile(
    r"<item>.*?<title>(?P<title>.*?)</title>.*?<link>(?P<url>https?://[^<]+)</link>.*?</item>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class _Budget:
    searches: int = 0
    pages: int = 0
    actions: int = 0
    elapsed_seconds: float = 0.0
    active_batches: int = 0
    active_started_at: float | None = None


class BrowserGateway:
    """Stateful per-MCP-process quota and safety boundary."""

    def __init__(
        self,
        *,
        client: AgentBrowserClient | None = None,
        resolver=None,
        clock=time.monotonic,
        max_searches: int | None = None,
        max_pages: int | None = None,
        max_actions: int | None = None,
        max_elapsed_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self.client = client or AgentBrowserClient()
        self._resolver = resolver
        self._clock = clock
        self._budget = _Budget()
        self._lock = asyncio.Lock()
        self._execution_id = uuid.uuid4().hex
        self._operation = 0
        self._max_searches = max_searches if max_searches is not None else settings.research_max_searches
        self._max_pages = max_pages if max_pages is not None else settings.research_max_pages
        self._max_actions = max_actions if max_actions is not None else settings.research_max_actions
        self._max_elapsed_seconds = (
            max_elapsed_seconds
            if max_elapsed_seconds is not None
            else settings.research_max_elapsed_seconds
        )
        if min(
            self._max_searches,
            self._max_pages,
            self._max_actions,
            self._max_elapsed_seconds,
        ) < 1:
            raise ValueError("Browser research safety budgets must be positive.")

    async def browser_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search public pages without a search API and return validated HTTPS links."""
        query = query.strip() if isinstance(query, str) else ""
        if not query or len(query) > 500:
            return self._error("invalid_query", "Query must contain 1 to 500 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            return self._error("invalid_limit", "Limit must be an integer from 1 to 10")
        try:
            await self._charge(searches=1, actions=1)
        except RuntimeError as error:
            return self._error("quota_exceeded", str(error))

        engines = (
            ("duckduckgo", "https://html.duckduckgo.com/html/?" + urlencode({"q": query})),
            (
                "bing",
                "https://www.bing.com/search?"
                + urlencode(
                    {"q": query, "format": "rss", "adlt": "strict", "setlang": "en-US", "cc": "US"}
                ),
            ),
        )
        failures: list[str] = []
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        used_engines: list[str] = []
        for engine, search_url in engines:
            try:
                candidates = await self._search_page(search_url, min(5, limit - len(results)))
            except (AgentBrowserError, UrlPolicyError) as error:
                failures.append(type(error).__name__)
                continue
            added = False
            for candidate in candidates:
                if candidate["url"] in seen:
                    continue
                seen.add(candidate["url"])
                results.append(candidate)
                added = True
                if len(results) >= limit:
                    break
            if added:
                used_engines.append(engine)
            else:
                failures.append("no_results")
            if len(results) >= limit:
                break
        if results:
            return {
                "status": "ok",
                "engine": used_engines[0],
                "engines": used_engines,
                "query": query,
                "results": results,
            }
        return {
            "status": "unavailable",
            "error": {"code": "search_unavailable", "message": "Public search pages returned no usable results"},
            "query": query,
            "attempts": len(failures),
        }

    async def browser_read(self, urls: list[str]) -> dict[str, Any]:
        """Read up to four explicitly selected, public HTTPS pages."""
        if not isinstance(urls, list) or not urls or len(urls) > MAX_URLS_PER_READ:
            return self._error("invalid_urls", f"Provide between 1 and {MAX_URLS_PER_READ} URLs")
        if any(not isinstance(url, str) for url in urls):
            return self._error("invalid_urls", "Every URL must be a string")
        try:
            await self._charge(pages=len(urls), actions=len(urls))
        except RuntimeError as error:
            return self._error("quota_exceeded", str(error))

        pages = []
        for requested_url in urls:
            try:
                normalized = await self._validate(requested_url)
                pages.append(await self._read_page(normalized))
            except UrlPolicyError as error:
                pages.append(
                    {
                        "status": "unavailable",
                        "requested_url": requested_url,
                        "error": {"code": "url_rejected", "message": str(error)},
                    }
                )
            except AgentBrowserError:
                pages.append(
                    {
                        "status": "unavailable",
                        "requested_url": requested_url,
                        "error": {"code": "navigation_failed", "message": "The public page could not be read"},
                    }
                )
        return {"status": "ok" if any(page["status"] == "ok" for page in pages) else "unavailable", "pages": pages}

    async def _search_page(self, search_url: str, limit: int) -> list[dict[str, str]]:
        normalized = await self._validate(search_url)
        host = hostname_for_url(normalized)
        session = self._next_session()
        try:
            results = await self._run_browser_batch(
                session,
                host,
                [
                    ["open", normalized],
                    ["get", "url"],
                    ["snapshot", "-i", "--urls", "-c", "-d", "5"],
                    ["get", "text", "body"],
                    ["close"],
                ],
            )
            final_payload = results[1]
            await self._validate(output_text(final_payload, "url"))
            snapshot = results[2]
            body = results[3]
            searchable_text = "\n".join(
                (output_text(snapshot, "snapshot", "text"), output_text(body, "content", "text"))
            )
            return await self._parse_results(searchable_text, normalized, limit)
        except Exception:
            await self.client.close(session, host)
            raise

    async def _read_page(self, normalized: str) -> dict[str, Any]:
        host = hostname_for_url(normalized)
        session = self._next_session()
        try:
            results = await self._run_browser_batch(
                session,
                host,
                [
                    ["open", normalized],
                    ["get", "url"],
                    ["get", "title"],
                    ["scroll", "down", "800"],
                    ["scroll", "down", "800"],
                    ["get", "text", "body"],
                    ["close"],
                ],
            )
            final_payload = results[1]
            final_url = await self._validate(output_text(final_payload, "url"))
            # The CLI allowlist blocks cross-domain redirects before content is read.
            if hostname_for_url(final_url) != host:
                raise AgentBrowserError("cross-domain redirect requires a separate browser_read call")
            title_payload = results[2]
            # v0.27.3 predates the `read` command; rendered body text is the
            # compatible, browser-backed extraction path for the pinned CLI.
            content_payload = results[5]
            content = output_text(content_payload, "content", "text")[:MAX_PAGE_CHARACTERS]
            if not content.strip():
                raise AgentBrowserError("page did not expose readable text")
            return {
                "status": "ok",
                "requested_url": normalized,
                "url": final_url,
                "title": output_text(title_payload, "title", "text")[:500],
                "content": content,
                "content_is_untrusted": True,
                "truncated": len(output_text(content_payload, "content", "text")) > MAX_PAGE_CHARACTERS,
            }
        except Exception:
            await self.client.close(session, host)
            raise

    async def _parse_results(self, text: str, base_url: str, limit: int) -> list[dict[str, str]]:
        candidates: list[tuple[str, str]] = list(_MARKDOWN_LINK.findall(text))
        candidates.extend(
            (match.group("title") or "Search result", match.group("url")) for match in _SNAPSHOT_LINK.finditer(text)
        )
        candidates.extend((match.group("title"), match.group("url")) for match in _RSS_ITEM.finditer(text))
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for title, raw_url in candidates:
            candidate = _unwrap_search_redirect(urljoin(base_url, raw_url.rstrip(".,")))
            try:
                normalized = await self._validate(candidate)
            except UrlPolicyError:
                continue
            if normalized in seen or not _is_discovery_result(normalized, hostname_for_url(base_url)):
                continue
            seen.add(normalized)
            results.append({"title": _clean_title(title), "url": normalized})
            if len(results) >= limit:
                break
        return results

    async def _charge(self, *, searches: int = 0, pages: int = 0, actions: int = 0) -> None:
        async with self._lock:
            if self._budget.elapsed_seconds >= self._max_elapsed_seconds:
                raise RuntimeError("Browser research exceeded its configured time budget")
            if self._budget.searches + searches > self._max_searches:
                raise RuntimeError("Browser research exceeded its configured search budget")
            if self._budget.pages + pages > self._max_pages:
                raise RuntimeError("Browser research exceeded its configured page budget")
            if self._budget.actions + actions > self._max_actions:
                raise RuntimeError("Browser research exceeded its configured action budget")
            self._budget.searches += searches
            self._budget.pages += pages
            self._budget.actions += actions

    async def _validate(self, url: str) -> str:
        kwargs = {"resolver": self._resolver} if self._resolver is not None else {}
        return await asyncio.to_thread(validate_public_https_url, url, **kwargs)

    async def _run_browser_batch(self, session: str, host: str, commands: list[list[str]]) -> list[Any]:
        async with self._lock:
            now = self._clock()
            active_elapsed = (
                max(0.0, now - self._budget.active_started_at)
                if self._budget.active_started_at is not None
                else 0.0
            )
            remaining = self._max_elapsed_seconds - self._budget.elapsed_seconds - active_elapsed
            if remaining <= 0:
                raise AgentBrowserError("browser research time budget expired")
            if self._budget.active_batches == 0:
                self._budget.active_started_at = now
            self._budget.active_batches += 1
        try:
            return await asyncio.wait_for(self.client.run_batch(session, host, commands), timeout=remaining)
        except TimeoutError as error:
            raise AgentBrowserError("browser research time budget expired") from error
        finally:
            async with self._lock:
                self._budget.active_batches -= 1
                if self._budget.active_batches == 0 and self._budget.active_started_at is not None:
                    self._budget.elapsed_seconds += max(
                        0.0, self._clock() - self._budget.active_started_at
                    )
                    self._budget.active_started_at = None

    def _next_session(self) -> str:
        self._operation += 1
        return f"learning-{self._execution_id}-{self._operation}"

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"status": "unavailable", "error": {"code": code, "message": message}}


def _unwrap_search_redirect(url: str) -> str:
    parsed = urlsplit(url)
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    if hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if target:
            return unquote(target)
    return url


def _clean_title(value: str) -> str:
    return " ".join(value.replace("\\", "").split())[:300] or "Search result"


def _is_discovery_result(url: str, search_host: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    blocked_search_hosts = ("duckduckgo.com", "bing.com")
    return not any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_search_hosts)
