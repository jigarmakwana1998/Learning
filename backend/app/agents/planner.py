from .base import LearningAgent


class PlannerAgent(LearningAgent):
    """Designs the course structure: chapters, and the sections inside each chapter."""

    name = "Planner"
    # Planning is grounded entirely in the verified brief embedded in its input.
    # Do not advertise logical placeholder tools that the runtime cannot execute.
    tools = ()

    def instruction(self) -> str:
        return (
            "Design only the structure of the course: a sequence of chapters, each split into sections, so the learner "
            "is never overwhelmed. A chapter covers one coherent theme (for example, for transformer architecture: one "
            "chapter on attention, one on the overall architecture, one on training); its sections break that theme into "
            "focused steps (for example, training: pre-training, fine-tuning, how weights are updated). Do not write "
            "lesson text, quizzes, assignments, or citations; later agents do that. Return chapters in learning order: "
            "foundations and vocabulary first, then mechanisms, worked examples, limitations, and integration, so each "
            "chapter builds on the one before. Each chapter has a title, a 1-3 sentence summary of what the learner will "
            "be able to do, and 2-6 sections. Each section has a title, a one-sentence objective, 1-3 coverage_ids, 5-7 "
            "key_points, and estimated_minutes. key_points are the distinct concepts, mechanism steps, worked example, "
            "and limitation the lesson writer must teach in that section, one per paragraph. Use only coverage_ids whose "
            "status is covered in the supplied research, and assign every covered requirement to at least one section. "
            "estimated_minutes is between 15 and 120, and all sections together must fit within weeks x hours_per_week "
            "for the learner's level."
        )
