"""Run one authenticated, browser-backed course generation against the local app.

This is intentionally opt-in because it consumes provider quota and public websites can
change. It uses an ignored local SQLite database and prints only course/source metadata.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")
os.environ["AGENT_PROVIDER"] = "gemini-cli"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./learning_live_smoke.db"
os.environ["LOCAL_AUTH"] = "true"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> None:
    topic = os.getenv("LIVE_SMOKE_TOPIC", "Attention layers in large language models")
    email = f"live-smoke-{uuid4().hex}@example.com"
    password = "LiveSmokePass123!"

    with TestClient(app) as client:
        registration = client.post(
            "/auth/register",
            json={"email": email, "password": password},
        )
        registration.raise_for_status()
        headers = {
            "Authorization": f"Bearer {registration.json()['access_token']}"
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
        summary = {
            "run_id": course["id"],
            "provider": course["provider"],
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
            "quiz_items": len(course["assessment"]["quiz_items"]),
            "assignment": course["assessment"]["assignment"]["title"],
            "sessions": course["sessions"],
        }
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
