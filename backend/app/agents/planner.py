from .base import LearningAgent


class PlannerAgent(LearningAgent):
    name = "Planner"
    # Planning is grounded entirely in the verified brief embedded in its input.
    # Do not advertise logical placeholder tools that the runtime cannot execute.
    tools = []

    def instruction(self) -> str:
        return (
            "Build the complete learner-facing course using only the supplied browser-verified research URLs. Return exactly "
            "one JSON object and no markdown: "
            "{curriculum:[{week,title,outcomes,source_urls,overview,estimated_hours,lessons}]}, where each lesson is "
            "{id,title,objective,content,practice,estimated_minutes,source_urls}. Return exactly the requested number of weeks, "
            "numbered once from 1 through the requested timeline, with at least two complete lessons per week. Respect the "
            "learner level and weekly-hour budget. Sequence foundations and vocabulary before mechanisms, worked examples, "
            "limitations, integration, and synthesis; make each week depend meaningfully on the prior one. Every lesson content "
            "field must be roughly 350-700 words and teach the actual topic with concrete explanations, worked examples, "
            "common mistakes, and validation checkpoints, not describe a generic study process. "
            "Every lesson must include a specific practice task and cite one or more source_urls. Copy URLs exactly from the "
            "supplied research object; never invent, shorten, rewrite, or cite any other URL. Every module must include a primary "
            "source where the verified set provides one and an applied exercise."
        )
