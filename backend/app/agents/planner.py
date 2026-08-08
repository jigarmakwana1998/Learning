from .base import LearningAgent


class PlannerAgent(LearningAgent):
    name = "Planner"
    # Planning is grounded entirely in the verified brief embedded in its input.
    # Do not advertise logical placeholder tools that the runtime cannot execute.
    tools = ()

    def instruction(self) -> str:
        return (
            "Build the complete learner-facing course using only the supplied browser-verified research URLs. Return exactly "
            "one JSON object and no markdown: "
            "{curriculum:[{week,title,outcomes,source_urls,overview,estimated_hours,lessons}],assessment:{quiz_items,assignment,project}}, where each lesson is "
            "{id,title,objective,paragraphs:[{text,source_urls}],practice,estimated_minutes,source_urls}. Return exactly the "
            "requested number of weeks, "
            "numbered once from 1 through the requested timeline, with at least two complete lessons per week. Respect the "
            "learner level and weekly-hour budget. Sequence foundations and vocabulary before mechanisms, worked examples, "
            "limitations, integration, and synthesis; make each week depend meaningfully on the prior one. Every lesson must "
            "contain 4-7 distinct, substantial paragraphs or short subsections totaling roughly 1,200-1,800 words (about 3-4 normal pages). "
            "Teach the actual topic using the supplied source "
            "key_points: define it, explain why it matters, trace its mechanism, place it in the wider architecture, show a worked "
            "example, and cover limitations or current practice as appropriate. Never repeat the learner's prompt as filler and "
            "never repeat a sentence or paragraph. Every paragraph must cite 1-3 exact source_urls that directly support that "
            "paragraph. Synthesis from multiple sources should cite all of them. Every lesson must include a specific practice "
            "task. Use multiple sources when they add complementary evidence, but allow one authoritative source to support a "
            "lesson when it covers the required material. Copy URLs exactly from the supplied research object; never invent, "
            "shorten, rewrite, or cite any other URL. Omit unsupported coverage areas and state relevant limitations from research "
            "warnings. Prefer primary sources when relevant and include an applied exercise. The assessment must contain 2-5 quiz_items "
            "per week. Each quiz item is {id,module_week,prompt,choices,correct_answer,explanation}; use 3-5 distinct choices, "
            "make correct_answer exactly match one choice, and write a specific teaching explanation. The assignment is "
            "{title,prompt,deliverables,rubric} with 2-8 concrete deliverables and 2-8 observable rubric criteria. The project "
            "must be a substantial capstone prompt tied to the course outcomes. Do not emit generic study advice or placeholders."
        )
