from .base import LearningAgent


class LessonWriterAgent(LearningAgent):
    """Expands one planned lesson into substantive, paragraph-cited teaching."""

    name = "LessonWriter"
    tools = ()

    def instruction(self) -> str:
        return (
            "Write the complete body for exactly one planned lesson using only the supplied browser-verified research. "
            "Populate the structured lesson and paragraph fields. Copy the "
            "lesson id exactly. Return exactly one distinct paragraph for each item in lesson_draft.section_plan, in the same "
            "order, with roughly 200-300 substantive words per paragraph (1,200-1,800 words for six items). Cover every item in "
            "context.coverage_targets in at least one "
            "paragraph. Each paragraph must declare only the coverage_ids it actually teaches. Teach the topic rather than "
            "describing a study plan: establish the definition and motivation, explain "
            "the mechanism step by step, connect it to the wider architecture, give a concrete worked example, and discuss "
            "limitations or current practice where relevant. Use the draft only as an outline; expand it with the supplied "
            "source key points without repeating sentences or the learner prompt. Every paragraph must carry 1-3 exact "
            "source_urls that directly support it. Use multiple sources when they add complementary evidence, but do not add a "
            "second citation merely for diversity when one authoritative source covers the lesson. Copy URLs exactly "
            "from verified_sources, and for every declared coverage_id cite at least one URL listed in that target's "
            "supported_by. Never invent, shorten, or rewrite a URL and never add unsupported facts."
        )
