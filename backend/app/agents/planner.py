from .base import LearningAgent


class PlannerAgent(LearningAgent):
    name = "Planner"
    # Planning is grounded entirely in the verified brief embedded in its input.
    # Do not advertise logical placeholder tools that the runtime cannot execute.
    tools = ()

    def instruction(self) -> str:
        return (
            "Design the complete course architecture using only the supplied browser-verified research. A separate lesson "
            "writer will expand each lesson, so keep this response compact and do not write lesson prose. Populate the "
            "structured curriculum and assessment fields; each lesson is "
            "{id,title,objective,coverage_ids,section_plan,paragraphs:[],practice,estimated_minutes,source_urls}. Return exactly the "
            "requested number of weeks, "
            "numbered once from 1 through the requested timeline, with at least two complete lessons per week. Respect the "
            "learner level and weekly-hour budget. Sequence foundations and vocabulary before mechanisms, worked examples, "
            "limitations, integration, and synthesis; make each week depend meaningfully on the prior one. Map every covered "
            "research requirement to at least one lesson via coverage_ids, and do not use missing or partial requirements. A "
            "module's coverage_ids must equal the union of its lesson coverage_ids. Give each lesson 1-3 coherent coverage_ids "
            "and a 5-7 item section_plan that names the actual concepts, mechanism steps, worked example, architectural connection, "
            "and limitations or decisions the writer must teach. Use source_urls that appear in supported_by for those coverage "
            "requirements. Leave paragraphs as an empty array. Every lesson must include a specific practice "
            "task. Use multiple sources when they add complementary evidence, but allow one authoritative source to support a "
            "lesson when it covers the required material. Copy URLs exactly from the supplied research object; never invent, "
            "shorten, rewrite, or cite any other URL. Omit unsupported coverage areas and state relevant limitations from research "
            "warnings. Prefer primary sources when relevant and include an applied exercise. The assessment must contain 2-5 quiz_items "
            "per week. Each quiz item is {id,module_week,prompt,choices,correct_answer,explanation}; use 3-5 distinct choices, "
            "make correct_answer exactly match one choice, and write a specific teaching explanation. The assignment is "
            "{title,prompt,deliverables,rubric} with 2-8 concrete deliverables and 2-8 observable rubric criteria. The project "
            "must be a substantial capstone prompt tied to the course outcomes. Do not emit generic study advice or placeholders."
        )
