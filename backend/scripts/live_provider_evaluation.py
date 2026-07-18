"""Opt-in provider evaluation; never executed by default CI."""
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter

from app.harness.providers.factory import get_runtime


async def main():
    provider = os.environ.get("AGENT_PROVIDER")
    if provider not in {"codex", "gemini-cli", "antigravity-cli"}: raise SystemExit("Set AGENT_PROVIDER to an authenticated real provider")
    fixtures = json.loads((Path(__file__).parents[1] / "evaluations/fixtures.json").read_text())
    runtime, results = get_runtime(provider), []
    for fixture in fixtures:
        started = perf_counter()
        try:
            output = await runtime.execute(json.dumps({"role": "Researcher", "learner_goal": fixture, "return": "JSON sources"}))
            results.append({"fixture": fixture["name"], "success": True, "schema_valid": isinstance(output, dict), "duration_ms": round((perf_counter() - started) * 1000), "source_count": len(output.get("sources", []))})
        except Exception as error:
            results.append({"fixture": fixture["name"], "success": False, "duration_ms": round((perf_counter() - started) * 1000), "failure": str(error)})
    report = Path("evaluation-report.json"); report.write_text(json.dumps(results, indent=2)); print(report)


if __name__ == "__main__": asyncio.run(main())
