from .base import LearningAgent


class ExaminerAgent(LearningAgent):
    name = "Examiner"
    tools = ["get_progress", "record_assessment"]

    def instruction(self) -> str:
        return "Return JSON: {quiz,assignment,project}. Design assessment from the curriculum and use outcomes to recommend review, acceleration, or extra practice."
