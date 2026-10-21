"""Browser server settings, read from the environment of the process that runs it."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserSettings:
    # Internal SearXNG JSON search; unset falls back to scraping public search pages.
    searxng_url: str | None
    research_max_searches: int
    research_max_pages: int
    research_max_actions: int
    research_max_elapsed_seconds: int


def browser_settings() -> BrowserSettings:
    return BrowserSettings(
        searxng_url=os.getenv("SEARXNG_URL") or None,
        research_max_searches=int(os.getenv("RESEARCH_MAX_SEARCHES", "20")),
        research_max_pages=int(os.getenv("RESEARCH_MAX_PAGES", "40")),
        research_max_actions=int(os.getenv("RESEARCH_MAX_ACTIONS", "60")),
        research_max_elapsed_seconds=int(os.getenv("RESEARCH_MAX_ELAPSED_SECONDS", "600")),
    )
