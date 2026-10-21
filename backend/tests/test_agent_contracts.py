import json

import pytest

from app.agents import (
    ResearchCoverageEvaluatorAgent, ResearchQueryPlannerAgent, ResearchSelectorAgent,
    ResearchSynthesisAgent,
)
from app.schemas.learning import LearningGoal


@pytest.mark.parametrize(
    "agent",
    [
        ResearchQueryPlannerAgent(),
        ResearchSelectorAgent(),
        ResearchSynthesisAgent(),
        ResearchCoverageEvaluatorAgent(),
    ],
)
def test_agents_emit_machine_readable_prompt_contracts(agent):
    payload = json.loads(agent.build_prompt(LearningGoal(topic="Python", weeks=4)))
    assert payload["agent"] == agent.name
    assert payload["tools"] == list(agent.tools)
    assert payload["learner_goal"]["topic"] == "Python"
