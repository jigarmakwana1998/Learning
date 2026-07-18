from .base import LearningAgent


class PlannerAgent(LearningAgent):
    name = "Planner"
    tools = ["rank_sources", "get_progress"]

    def instruction(self) -> str:
        return "Filter supplied research and return JSON: {curriculum:[{week,title,outcomes,source_urls}]}, respecting learner level, weekly hours, and timeline."
