from .base import LearningAgent


class PlannerAgent(LearningAgent):
    """Step 1 of planning: the course outline (chapters only)."""

    name = "Planner"
    # Planning is grounded entirely in the verified brief embedded in its input.
    # Do not advertise logical placeholder tools that the runtime cannot execute.
    tools = ()

    def instruction(self) -> str:
        return (
            "Outline the course as a sequence of chapters so the learner is never overwhelmed. A chapter covers one "
            "coherent theme (for example, for transformer architecture: one chapter on attention, one on the overall "
            "architecture, one on training). Return only the chapters; their sections are planned separately, one chapter "
            "at a time. Order chapters for learning: foundations and vocabulary first, then mechanisms, worked examples, "
            "limitations, and integration, so each chapter builds on the one before. Do not number chapter titles; the "
            "app numbers them. Give each chapter a summary of what the learner will be able to do and the coverage_ids it "
            "teaches. Use only coverage_ids whose status is covered in the supplied research, and assign every covered "
            "requirement to at least one chapter."
        )


class ChapterPlannerAgent(LearningAgent):
    """Step 2 of planning, once per chapter: that chapter's sections."""

    name = "PlannerChapter"
    tools = ()

    def instruction(self) -> str:
        return (
            "Plan the sections of one chapter, context.chapter, within the full course outline in context.outline. "
            "Sections break the chapter's theme into focused steps (for example, a training chapter: pre-training, "
            "fine-tuning, how weights are updated). Stay within this chapter's theme: do not repeat sections listed in "
            "context.planned_sections or cover topics that belong to other chapters in the outline. Do not write lesson "
            "text, quizzes, assignments, or citations. Do not number section titles. Give each section the coverage_ids "
            "it teaches, chosen from context.chapter.coverage_ids, its key_points (the concepts, mechanism steps, worked "
            "example, and limitation the lesson writer must teach, one paragraph each) drawn from context.research, and "
            "estimated_minutes. Together the chapter's sections must teach every one of its coverage_ids; aim to fit them "
            "within context.chapter_minutes, this chapter's share of the learner's time."
        )
