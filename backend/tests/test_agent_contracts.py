import json

import pytest

from app.agents import ExaminerAgent, PlannerAgent, ResearcherAgent
from app.schemas.learning import LearningGoal
from app.mcp.tools import LEARNING_TOOLS, RESEARCH_TOOLS


@pytest.mark.parametrize("agent", [ResearcherAgent(), PlannerAgent(), ExaminerAgent()])
def test_agents_emit_machine_readable_prompt_contracts(agent):
    payload = json.loads(agent.build_prompt(LearningGoal(topic="Python", weeks=4)))
    assert payload["agent"] == agent.name
    assert payload["tools"] == agent.tools
    assert payload["learner_goal"]["topic"] == "Python"


def test_mcp_capabilities_are_allowlisted_and_described():
    tools = RESEARCH_TOOLS + LEARNING_TOOLS
    assert {tool.name for tool in tools} == {"search_web", "fetch_source", "rank_sources", "get_progress", "record_assessment"}
    assert all(tool.input_schema and tool.description for tool in tools)
