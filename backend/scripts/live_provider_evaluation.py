"""Opt-in evaluation through the same LiteLLM gateway used by live agents."""
import asyncio
import json
from pathlib import Path
from time import perf_counter

from app.core.config import get_settings
from app.harness.providers.factory import get_runtime


async def main():
    fixtures = json.loads((Path(__file__).parents[1] / "evaluations/fixtures.json").read_text())
    harness = get_settings().agent_harness
    runtime, results = get_runtime(harness), []
    for fixture in fixtures:
        started = perf_counter()
        try:
            execution = await runtime.execute(json.dumps({"role": "Researcher", "learner_goal": fixture, "return": "JSON sources"}))
            output = execution.payload
            results.append({"fixture": fixture["name"], "success": True, "schema_valid": isinstance(output, dict), "duration_ms": round((perf_counter() - started) * 1000), "source_count": len(output.get("sources", []))})
        except (OSError, RuntimeError, ValueError) as error:
            results.append({"fixture": fixture["name"], "success": False, "duration_ms": round((perf_counter() - started) * 1000), "failure": str(error)})
    report = Path("evaluation-report.json"); report.write_text(json.dumps(results, indent=2)); print(report)


if __name__ == "__main__": asyncio.run(main())
