from .base import LearningAgent


class ResearcherAgent(LearningAgent):
    name = "Researcher"
    tools = ["search_web", "fetch_source", "rank_sources"]

    def instruction(self) -> str:
        return (
            "Research a rigorous, learner-ready source set. Return exactly one JSON object and no markdown: "
            "{topic,sources:[{title,url,kind,rationale}]}. Provide 8-12 directly reachable, real URLs, each with a "
            "specific rationale. Cover primary research papers, authoritative documentation, a book or chapter, a lecture "
            "or course, and high-quality explanatory articles/blogs; use kind values documentation, paper, book, lecture, "
            "article, or repository. Prefer original papers and canonical publishers. Never invent, shorten, or use search URLs."
        )
