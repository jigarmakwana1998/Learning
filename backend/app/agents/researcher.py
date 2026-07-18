from .base import LearningAgent


class ResearcherAgent(LearningAgent):
    name = "Researcher"
    tools = ["search_web", "fetch_source", "rank_sources"]

    def instruction(self) -> str:
        return "Research credible online sources: official docs, open-source repos, papers, lectures, books, and articles. Return JSON: {topic,sources:[{title,url,kind,rationale}]}. Never invent URLs."
