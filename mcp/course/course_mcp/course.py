"""Course content the agent writes, and the citation rules write_section enforces."""

import re
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


class AgentOutput(BaseModel):
    # Whitespace-only strings must not satisfy a minimum length.
    model_config = ConfigDict(str_strip_whitespace=True)


class Cite(AgentOutput):
    passage: str = Field(pattern=r"^s\d+\.p\d+$", description="Passage id from read_source or search_sources, e.g. s2.p7.")
    quote: str = Field(min_length=8, description="Words copied exactly from that passage that state the fact.")


class Sentence(AgentOutput):
    text: str = Field(min_length=2)
    kind: Literal["fact", "explanation"] = Field(
        description="fact: anything a source must back (a definition, how something works, a number, name or date). "
        "explanation: connecting or teaching text that states no new fact."
    )
    cites: list[Cite] = Field(default_factory=list, description="At least one for a fact.")


class WrittenSentence(Sentence):
    warning: str | None = None


class OutlineSection(AgentOutput):
    id: str = Field(min_length=1)
    title: str = Field(min_length=2)
    covers: list[str] = Field(min_length=1, description="Ids of the coverage items this section teaches.")


class Chapter(AgentOutput):
    id: str = Field(min_length=1)
    title: str = Field(min_length=2)
    sections: list[OutlineSection] = Field(min_length=1)


Paragraph = Annotated[list[Sentence], Field(min_length=1)]


def passages(text: str) -> list[str]:
    """A page's passages are its non-empty lines, so passage ids never change for the same text."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normal(text: str) -> str:
    return " ".join(text.translate(_QUOTES).split()).casefold()


def review(
    paragraphs: list[list[Sentence]], passage_text: Callable[[str], str | None]
) -> tuple[list[str], list[list[WrittenSentence]]]:
    """Problems that reject the section, and the sentences to save with any number warnings."""
    problems: list[str] = []
    written: list[list[WrittenSentence]] = []
    for p, paragraph in enumerate(paragraphs, 1):
        written.append([])
        for s, sentence in enumerate(paragraph, 1):
            where = f"paragraph {p} sentence {s}"
            if sentence.kind == "fact" and not sentence.cites:
                problems.append(f"{where} is a fact with no citation.")
            quotes = []
            for cite in sentence.cites:
                text = passage_text(cite.passage)
                if text is None:
                    problems.append(f"{where}: unknown passage {cite.passage}.")
                elif _normal(cite.quote) not in _normal(text):
                    problems.append(f"{where}: the quote is not in {cite.passage}; copy its words exactly.")
                else:
                    quotes.append(cite.quote)
            written[-1].append(WrittenSentence(**sentence.model_dump(), warning=_number_warning(sentence, quotes)))
    return problems, written


def _number_warning(sentence: Sentence, quotes: list[str]) -> str | None:
    numbers = NUMBER.findall(sentence.text)
    if not numbers:
        return None
    if not sentence.cites:
        return f"Uncited number {', '.join(numbers)}: a number is a fact; cite it."
    quoted = set(NUMBER.findall(" ".join(quotes)))
    missing = [number for number in numbers if number not in quoted]
    return f"Not in the cited source: {', '.join(missing)}." if missing else None


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
