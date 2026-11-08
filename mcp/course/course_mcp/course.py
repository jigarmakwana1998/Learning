"""Course content and descriptive progress, without automatic content grading."""

from pydantic import BaseModel, ConfigDict, Field


class AgentOutput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class Cite(AgentOutput):
    passage: str = Field(description="One passage id from read_source or search_sources, e.g. s2.p7.")
    quote: str = Field(default="", description="Optional excerpt from the passage.")


class Sentence(AgentOutput):
    text: str
    kind: str = "fact"
    cites: list[Cite] = Field(default_factory=list, description="Optional source references.")
    paragraph: int = Field(
        default=1,
        description="Paragraph number in the section, from 1; sentences with the same number form a paragraph.",
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
