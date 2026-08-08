from .base import LearningAgent


class LessonWriterAgent(LearningAgent):
    """Expands one planned lesson into substantive, paragraph-cited teaching."""

    name = "LessonWriter"
    tools = ()

    def instruction(self) -> str:
        return (
            "Write the complete body for exactly one planned lesson using only the supplied browser-verified research. "
            "Return exactly one JSON object and no markdown: {lesson:{id,paragraphs:[{text,source_urls}]}}. Copy the "
            "lesson id exactly. Return 5-7 distinct paragraphs, each 220-300 words, totaling 1,200-1,800 substantive "
            "words. Teach the topic rather than describing a study plan: establish the definition and motivation, explain "
            "the mechanism step by step, connect it to the wider architecture, give a concrete worked example, and discuss "
            "limitations or current practice where relevant. Use the draft only as an outline; expand it with the supplied "
            "source key points without repeating sentences or the learner prompt. Every paragraph must carry 1-3 exact "
            "source_urls that directly support it, and the lesson must synthesize at least two sources. Copy URLs exactly "
            "from verified_sources. Never invent, shorten, or rewrite a URL and never add unsupported facts."
        )
