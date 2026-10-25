"""stdio MCP server for one course version: its sources, its outline and its cited sections.

The course comes from COURSE_ID in the environment, never from a tool argument, so the agent can
only reach the sources of the research run it is building from.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from learning_db.models import AgentRun, Course, LearningRequest, SourcePage
from learning_db.session import SessionLocal

from .course import Chapter, Paragraph, check, passages, review

READ_CHARACTERS = 6000

mcp = FastMCP("learning-course")


@dataclass
class Library:
    goal: dict
    coverage: list[dict]
    sources: list[dict]
    passages: dict[str, str]


_library: Library | None = None


async def library() -> Library:
    """The run's goal, coverage and sources; fixed for the life of this process."""
    global _library
    if _library is None:
        async with SessionLocal() as db:
            course = await db.get(Course, os.environ["COURSE_ID"])
            research = await db.get(AgentRun, course.research_run_id)
            request = await db.get(LearningRequest, research.learning_request_id)
            pages = (
                await db.scalars(
                    select(SourcePage).where(SourcePage.research_run_id == research.id).order_by(SourcePage.position)
                )
            ).all()
        saved = {page["url"]: page for page in research.result["pages"]}
        sources, texts = [], {}
        for page in pages:
            lines = passages(page.text)
            texts.update({f"s{page.position}.p{n}": line for n, line in enumerate(lines, 1)})
            info = saved.get(page.url, {})
            sources.append({
                "id": f"s{page.position}",
                "title": page.title,
                "url": page.url,
                "kind": info.get("kind"),
                "why": info.get("why"),
                "covers": info.get("covers", []),
                "passages": len(lines),
            })
        _library = Library(
            goal={"topic": request.topic, "level": request.level, "total_hours": request.hours_per_week * request.weeks},
            coverage=research.result["coverage"],
            sources=sources,
            passages=texts,
        )
    return _library


@mcp.tool()
async def list_sources() -> dict:
    """The learner's goal, the coverage items to teach, and the source pages research saved for them."""
    lib = await library()
    return {"goal": lib.goal, "coverage": lib.coverage, "sources": lib.sources}


@mcp.tool()
async def read_source(source_id: str, start: int = 1) -> dict:
    """Numbered passages of one source from passage `start`; pass `next` back as `start` to read on."""
    lib = await library()
    source = next((item for item in lib.sources if item["id"] == source_id), None)
    if source is None:
        return {"error": f"Unknown source {source_id}. Use an id from list_sources."}
    result, size, number = [], 0, max(start, 1)
    while number <= source["passages"] and (not result or size < READ_CHARACTERS):
        text = lib.passages[f"{source_id}.p{number}"]
        result.append({"id": f"{source_id}.p{number}", "text": text})
        size, number = size + len(text), number + 1
    return {
        "source": source_id,
        "untrusted": True,
        "passages": result,
        "next": number if number <= source["passages"] else None,
    }


@mcp.tool()
async def search_sources(query: str, limit: int = 8) -> dict:
    """Passages from any source that share the most words with the query."""
    words = {word for word in re.findall(r"\w+", query.casefold()) if len(word) > 2}
    lib = await library()
    scored = []
    for passage_id, text in lib.passages.items():
        score = len(words & set(re.findall(r"\w+", text.casefold())))
        if score:
            scored.append((score, passage_id, text))
    scored.sort(key=lambda item: -item[0])
    return {"untrusted": True, "passages": [{"id": pid, "text": text} for _, pid, text in scored[: max(1, limit)]]}


@mcp.tool()
async def set_outline(chapters: list[Chapter]) -> str:
    """Set the course's chapters and sections. Replaces the outline; sections already written are kept by id."""
    async with SessionLocal() as db:
        course = await db.get(Course, os.environ["COURSE_ID"])
        course.chapters = [chapter.model_dump() for chapter in chapters]
        await db.commit()
    return f"Outline saved: {len(chapters)} chapters, {sum(len(c.sections) for c in chapters)} sections."


@mcp.tool()
async def write_section(section_id: str, paragraphs: list[Paragraph]) -> str:
    """Write or replace one outlined section. Every fact sentence cites a passage with an exact quote."""
    lib = await library()
    written = review(paragraphs, lib.passages.get)
    async with SessionLocal() as db:
        course = await db.get(Course, os.environ["COURSE_ID"])
        outlined = {section.id for chapter in course.chapters for section in Chapter(**chapter).sections}
        course.sections = {**course.sections, section_id: [[s.model_dump() for s in p] for p in written]}
        await db.commit()
    reply = f"Wrote {section_id}: {sum(len(p) for p in written)} sentences."
    if section_id not in outlined:
        reply += f" {section_id} is not in the outline, so the learner will not see it; use an outline id."
    if warnings := [f"paragraph {i} sentence {j}: {s.warning}" for i, p in enumerate(written, 1) for j, s in enumerate(p, 1) if s.warning]:
        reply += " Warnings, highlighted for the learner until you fix them:\n- " + "\n- ".join(warnings)
    return reply


@mcp.tool()
async def check_course() -> dict:
    """Sections not yet written, coverage items no written section teaches, and open number warnings."""
    lib = await library()
    async with SessionLocal() as db:
        course = await db.get(Course, os.environ["COURSE_ID"])
    chapters = [Chapter(**chapter) for chapter in course.chapters]
    return check(chapters, course.sections, [item["id"] for item in lib.coverage])


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
