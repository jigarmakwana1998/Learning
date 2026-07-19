from .base import LearningAgent


class PlannerAgent(LearningAgent):
    name = "Planner"
    tools = ["rank_sources", "get_progress"]

    def instruction(self) -> str:
        return (
            "Build a complete study plan using only the supplied research URLs. Return exactly one JSON object and no markdown: "
            "{curriculum:[{week,title,outcomes,source_urls,overview,estimated_hours,lessons}]}, where each lesson is "
            "{id,title,objective,content,practice,estimated_minutes}. Respect learner level, weekly hours, and timeline. "
            "Sequence foundations, mechanisms, worked examples, limitations, and synthesis. Every week must include a primary "
            "source and an applied exercise; every lesson must have concrete explanatory content and a practice task."
        )
