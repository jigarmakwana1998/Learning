"""Course content the agent writes, and the citation warnings write_section attaches to it."""

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


class AgentOutput(BaseModel):
    # No length or format constraints: whatever the agent writes is saved and shown; citation problems become warnings.
    model_config = ConfigDict(str_strip_whitespace=True)


class Cite(AgentOutput):
    passage: str = Field(description="One passage id from read_source or search_sources, e.g. s2.p7.")
    quote: str = Field(description="Text copied exactly from that one passage that states the fact.")


class Sentence(AgentOutput):
    text: str
    kind: Literal["fact", "explanation"] = Field(
        default="fact",
        description="fact: anything a source must back (a definition, how something works, a number, name or date). "
        "explanation: connecting or teaching text that states no new fact.",
    )
    cites: list[Cite] = Field(default_factory=list, description="At least one for a fact.")
    paragraph: int = Field(
        default=1, description="Paragraph number in the section, from 1; sentences with the same number form a paragraph."
    )


class WrittenSentence(Sentence):
    warning: str | None = None


class OutlineSection(AgentOutput):
    id: str
    title: str = ""
    covers: list[str] = Field(default_factory=list, description="Ids of the coverage items this section teaches.")


class Chapter(AgentOutput):
    id: str
    title: str = ""
    sections: list[OutlineSection] = Field(default_factory=list)


def paragraphs(sentences: list[Sentence]) -> list[list[Sentence]]:
    """Group a section's sentences into paragraphs by their paragraph number, keeping their order."""
    grouped: dict[int, list[Sentence]] = {}
    for sentence in sentences:
        grouped.setdefault(sentence.paragraph, []).append(sentence)
    return [grouped[number] for number in sorted(grouped)]


def passages(text: str) -> list[str]:
    """A page's passages are its non-empty lines, so passage ids never change for the same text."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normal(text: str) -> str:
    # Models often double-escape backslashes in JSON, so a formula quote arrives with \\ where the page has \.
    return " ".join(text.replace("\\\\", "\\").translate(_QUOTES).split()).casefold()


def review(paragraphs: list[list[Sentence]], passage_text: Callable[[str], str | None]) -> list[list[WrittenSentence]]:
    """Every sentence is saved; citation problems become a warning the learner sees."""
    return [[_written(sentence, passage_text) for sentence in paragraph] for paragraph in paragraphs]


def _written(sentence: Sentence, passage_text: Callable[[str], str | None]) -> WrittenSentence:
    warnings, quotes = [], []
    if sentence.kind == "fact" and not sentence.cites:
        warnings.append("Fact with no citation.")
    for cite in sentence.cites:
        text = passage_text(cite.passage)
        if text is None:
            warnings.append(f"Unknown passage {cite.passage}.")
        elif _normal(cite.quote) not in _normal(text):
            warnings.append(f"Quote not found in {cite.passage}.")
        else:
            quotes.append(cite.quote)
    numbers = NUMBER.findall(sentence.text)
    if numbers and not sentence.cites and sentence.kind == "explanation":
        warnings.append(f"Uncited number {', '.join(numbers)}.")
    elif missing := [n for n in numbers if quotes and n not in set(NUMBER.findall(" ".join(quotes)))]:
        warnings.append(f"Not in the cited source: {', '.join(missing)}.")
    return WrittenSentence(**sentence.model_dump(), warning=" ".join(warnings) or None)


def check(chapters: list[Chapter], sections: dict, coverage_ids: list[str]) -> dict:
    """Sections still to write, coverage items no written section teaches, and open warnings."""
    planned = [section for chapter in chapters for section in chapter.sections]
    taught = {item for section in planned if section.id in sections for item in section.covers}
    warnings = [
        f"{section_id} paragraph {p} sentence {s}: {sentence['warning']}"
        for section_id, paragraphs in sections.items()
        for p, paragraph in enumerate(paragraphs, 1)
        for s, sentence in enumerate(paragraph, 1)
        if sentence.get("warning")
    ]
    return {
        "unwritten": [section.id for section in planned if section.id not in sections],
        "untaught": [item for item in coverage_ids if item not in taught],
        "warnings": warnings,
    }
