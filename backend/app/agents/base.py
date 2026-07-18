import json
from abc import ABC, abstractmethod

from app.schemas.learning import LearningGoal


class LearningAgent(ABC):
    name: str
    tools: list[str]

    @abstractmethod
    def instruction(self) -> str: ...

    def build_prompt(self, goal: LearningGoal, context: dict | None = None) -> str:
        return json.dumps({"agent": self.name, "instruction": self.instruction(), "tools": self.tools, "learner_goal": goal.model_dump(), "context": context or {}}, indent=2)
