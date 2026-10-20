"""Offline gate for the checked-in evaluation corpus and agent contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.contracts import output_schema_for  # noqa: E402
from app.agents.lesson_writer import LessonWriterAgent  # noqa: E402
from app.agents.planner import PlannerAgent  # noqa: E402
from app.agents.research_pipeline import (  # noqa: E402
    ResearchQueryPlannerAgent,
    ResearchSynthesisAgent,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    assert len(fixtures) >= baseline["fixture_count"], "evaluation corpus shrank below its golden baseline"
    for fixture in fixtures:
        missing = set(baseline["required_fixture_fields"]) - set(fixture)
        assert not missing, f"fixture {fixture.get('name', '<unnamed>')} is missing: {sorted(missing)}"

    instructions = {
        "query_planner": ResearchQueryPlannerAgent().instruction(),
        "researcher": ResearchSynthesisAgent().instruction(),
        "planner": PlannerAgent().instruction(),
        "lesson_writer": LessonWriterAgent().instruction(),
    }
    for agent, terms in baseline["required_agent_output_terms"].items():
        missing = [term for term in terms if term.lower() not in instructions[agent].lower()]
        assert not missing, f"{agent} prompt no longer guarantees: {', '.join(missing)}"
    for role in (
        "ResearchQueryPlanner",
        "ResearchSelector",
        "ResearchSynthesisPart1",
        "ResearchCoverageRound1",
        "Planner",
        "LessonWriter",
    ):
        assert output_schema_for(role) is not None, f"{role} has no structured output contract"


if __name__ == "__main__":
    main()
