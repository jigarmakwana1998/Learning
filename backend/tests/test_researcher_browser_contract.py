import json

from app.agents import (
    ResearchCoverageEvaluatorAgent, ResearchQueryPlannerAgent, ResearchSelectorAgent,
    ResearchSynthesisAgent,
)
from app.schemas.learning import LearningGoal


def test_adaptive_research_agents_use_coverage_instead_of_source_counts():
    agents = [
        ResearchQueryPlannerAgent(), ResearchSelectorAgent(), ResearchSynthesisAgent(),
        ResearchCoverageEvaluatorAgent(),
    ]
    prompts = [json.loads(agent.build_prompt(LearningGoal(topic="Transformers"))) for agent in agents]

    assert all(prompt["tools"] == [] for prompt in prompts)
    instructions = " ".join(prompt["instruction"] for prompt in prompts)
    assert "coverage_requirements" in instructions
    assert "corroborate" in instructions
    # Counts and ranges belong in the output schemas, not the prompts.
    assert not any(rule in instructions for rule in ("5-10", "1-6 pages", "1-8", "20-60"))
    assert "untrusted evidence" in instructions
    assert "verified URLs" in instructions
    assert "exactly 12" not in instructions
    assert "8-12" not in instructions
