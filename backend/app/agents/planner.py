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
            "lesson text, quizzes, assignments, or citations; later agents do that. Order chapters for learning: "
            "foundations and vocabulary first, then mechanisms, worked examples, limitations, and integration, so each "
            "chapter builds on the one before. Do not number chapter or section titles; the app numbers them. Give each "
            "section the coverage_ids it teaches, its key_points (the concepts, mechanism steps, worked example, and "
            "limitation the lesson writer must teach, one paragraph each), and estimated_minutes. Use only coverage_ids "
            "whose status is covered in the supplied research, assign every covered requirement to at least one section, "
            "and keep the total time within weeks x hours_per_week for the learner's level."
        )
