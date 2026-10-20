"""Run one authenticated, browser-backed course generation against the local app.

This is intentionally opt-in because it consumes provider quota and public websites can
change. It uses an ignored local SQLite database and prints only course/source metadata.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./learning_live_smoke.db"
os.environ["AGENT_CHECKPOINT_DATABASE_URL"] = "sqlite+aiosqlite:///./learning_live_smoke_checkpoints.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> None:
    topic = os.getenv("LIVE_SMOKE_TOPIC", "Attention layers in large language models")
    email = os.environ["LIVE_SMOKE_EMAIL"]
    password = os.environ["LIVE_SMOKE_PASSWORD"]

    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        login.raise_for_status()
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        response = client.post(
            "/learning-runs",
            headers=headers,
            json={
                "topic": topic,
                "level": "beginner",
                "weeks": 1,
                "hours_per_week": 3,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Live course generation failed ({response.status_code}): {response.text[:2000]}"
            )
        course = response.json()
        modules = course["course"]["modules"]
        lessons = [lesson for module in modules for lesson in module["lessons"]]
        coverage = course["research"].get("coverage", [])
        required_coverage_ids = {item["requirement_id"] for item in coverage}
        module_coverage_ids = {
            requirement_id
            for module in modules
            for requirement_id in module.get("coverage_ids", [])
        }
        lesson_coverage_ids = {
            requirement_id
            for lesson in lessons
            for requirement_id in lesson.get("coverage_ids", [])
        }
        paragraph_coverage_ids = {
            requirement_id
            for lesson in lessons
            for paragraph in lesson["paragraphs"]
            for requirement_id in paragraph.get("coverage_ids", [])
        }
        completeness = {
            "research_coverage_satisfied": bool(coverage) and all(
                item["status"] == "covered" for item in coverage
            ),
            "all_requirements_mapped_to_modules": module_coverage_ids == required_coverage_ids,
            "all_requirements_mapped_to_lessons": lesson_coverage_ids == required_coverage_ids,
            "all_requirements_mapped_to_paragraphs": paragraph_coverage_ids == required_coverage_ids,
            "all_section_plans_expanded": all(
                len(lesson.get("section_plan", [])) == len(lesson["paragraphs"])
                for lesson in lessons
            ),
            "all_paragraphs_traced_and_cited": all(
                paragraph.get("heading")
                and paragraph.get("coverage_ids")
                and paragraph["source_urls"]
                for lesson in lessons
                for paragraph in lesson["paragraphs"]
            ),
            "all_lessons_page_length": all(
                1200 <= sum(len(paragraph["text"].split()) for paragraph in lesson["paragraphs"]) <= 1800
                for lesson in lessons
            ),
        }
        summary = {
            "run_id": course["id"],
            "harness": course["harness"],
            "topic": course["research"]["topic"],
            "sources": [
                {"title": source["title"], "url": source["url"], "kind": source["kind"]}
                for source in course["research"]["sources"]
            ],
            "visited_pages": len(course["research"].get("visited_sources", [])),
            "modules": len(modules),
            "lessons": len(lessons),
            "paragraphs": sum(len(lesson["paragraphs"]) for lesson in lessons),
            "lesson_word_counts": [
                sum(len(paragraph["text"].split()) for paragraph in lesson["paragraphs"])
                for lesson in lessons
            ],
            "all_paragraphs_cited": all(
                paragraph["source_urls"]
                for lesson in lessons
                for paragraph in lesson["paragraphs"]
            ),
            "coverage_requirements": len(required_coverage_ids),
            "completeness": completeness,
            "quiz_items": len(course["assessment"]["quiz_items"]),
            "assignment": course["assessment"]["assignment"]["title"],
            "sessions": course["sessions"],
        }
        print(json.dumps(summary, indent=2))
        failed_checks = [name for name, passed in completeness.items() if not passed]
        if failed_checks:
            raise RuntimeError(
                "Live course failed completeness checks: " + ", ".join(failed_checks)
            )


if __name__ == "__main__":
    main()
