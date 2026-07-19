"""Integration coverage for the learner-facing course workflow.

These tests intentionally use the deterministic ``mock`` provider.  They cover
the API contract a learner relies on after submitting a goal: a structured
course, readable lessons, durable lesson completion, a gradeable quiz, and
feedback for submitted work.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def learner_headers(client: TestClient, label: str) -> dict[str, str]:
    """Create an isolated learner so tests never depend on database cleanup."""
    email = f"{label}-{uuid4().hex}@example.com"
    password = "LearnerPass123!"
    registration = client.post("/auth/register", json={"email": email, "password": password})
    assert registration.status_code == 201, registration.text
    return {"Authorization": f"Bearer {registration.json()['access_token']}"}


def create_course(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/learning-runs",
        headers=headers,
        json={
            "topic": "Python functions",
            "level": "beginner",
            "weeks": 2,
            "hours_per_week": 3,
            "provider": "mock",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_learner_can_generate_study_and_complete_a_quiz_and_assignment() -> None:
    """The mock workflow is an executable, local end-to-end product slice."""
    with TestClient(app) as client:
        headers = learner_headers(client, "workflow")
        run = create_course(client, headers)

        assert run["provider"] == "mock"
        assert run["research"]["sources"]
        assert run["course"]["title"]
        modules = run["course"]["modules"]
        assert len(modules) == 2
        assert len(run["curriculum"]) == 2  # backward-compatible course summary

        lessons = [lesson for module in modules for lesson in module["lessons"]]
        assert lessons
        for lesson in lessons:
            assert lesson["id"]
            assert lesson["title"]
            assert lesson["objective"]
            assert lesson["content"]
            assert lesson["practice"]
            assert lesson["estimated_minutes"] >= 5

        first_lesson = lessons[0]
        progress = client.patch(
            f"/learning-runs/{run['id']}/progress",
            headers=headers,
            json={"lesson_id": first_lesson["id"], "completed": True},
        )
        assert progress.status_code == 200, progress.text
        progress_body = progress.json()
        assert progress_body["run_id"] == run["id"]
        assert progress_body["lesson_id"] == first_lesson["id"]
        assert progress_body["completed"] is True
        assert progress_body["completed_lessons"] == 1
        assert progress_body["total_lessons"] == len(lessons)

        questions = run["assessment"]["quiz_items"]
        assert questions
        # Answer keys are retained in the private run payload for grading and are
        # deliberately not leaked through the learner's course response.
        assert all("correct_answer" not in question and "explanation" not in question for question in questions)
        # The deterministic mock fixture keeps the documented best-practice answer
        # first so this test can exercise a perfect submission without an API leak.
        answers = [{"question_id": question["id"], "answer": question["choices"][0]} for question in questions]
        quiz = client.post(
            f"/learning-runs/{run['id']}/quiz-submissions",
            headers=headers,
            json={"quiz_id": "course-quiz", "answers": answers},
        )
        assert quiz.status_code == 200, quiz.text
        quiz_body = quiz.json()
        assert quiz_body["run_id"] == run["id"]
        assert quiz_body["total_questions"] == len(questions)
        assert quiz_body["correct_count"] == len(questions)
        assert quiz_body["score_percent"] == 100
        assert all(item["correct"] is True for item in quiz_body["feedback"])

        wrong_answers = [
            {
                "question_id": question["id"],
                "answer": question["choices"][1],
            }
            for question in questions
        ]
        incorrect_quiz = client.post(
            f"/learning-runs/{run['id']}/quiz-submissions",
            headers=headers,
            json={"quiz_id": "course-quiz", "answers": wrong_answers},
        )
        assert incorrect_quiz.status_code == 200, incorrect_quiz.text
        assert incorrect_quiz.json()["score_percent"] == 0
        assert all(item["correct"] is False for item in incorrect_quiz.json()["feedback"])

        submission = client.post(
            f"/learning-runs/{run['id']}/submissions",
            headers=headers,
            json={
                "kind": "assignment",
                "response": (
                    "I created three Python functions: one validates input, one "
                    "transforms it, and one prints the result. I tested each "
                    "function with normal and invalid inputs and documented my findings."
                ),
            },
        )
        assert submission.status_code == 200, submission.text
        submission_body = submission.json()
        assert submission_body["run_id"] == run["id"]
        assert submission_body["kind"] == "assignment"
        assert submission_body["content"]
        assert submission_body["status"] in {"submitted", "needs_revision", "accepted"}
        assert submission_body["feedback"]


def test_learning_workflow_requires_authentication_and_enforces_run_ownership() -> None:
    """A learner must never be able to mutate another learner's study data."""
    with TestClient(app) as client:
        owner = learner_headers(client, "owner")
        other_learner = learner_headers(client, "other")
        run = create_course(client, owner)
        question = run["assessment"]["quiz_items"][0]
        lesson = run["course"]["modules"][0]["lessons"][0]
        base = f"/learning-runs/{run['id']}"

        unauthenticated = client.patch(
            f"{base}/progress", json={"lesson_id": lesson["id"], "completed": True}
        )
        assert unauthenticated.status_code == 401

        assert client.patch(
            f"{base}/progress",
            headers=other_learner,
            json={"lesson_id": lesson["id"], "completed": True},
        ).status_code == 404
        assert client.post(
            f"{base}/quiz-submissions",
            headers=other_learner,
            json={"quiz_id": "course-quiz", "answers": [{"question_id": question["id"], "answer": question["choices"][0]}]},
        ).status_code == 404
        assert client.post(
            f"{base}/submissions",
            headers=other_learner,
            json={"kind": "assignment", "response": "This submission belongs to another learner and must not be accepted by this account."},
        ).status_code == 404


def test_lesson_progress_is_idempotent_and_can_be_reopened() -> None:
    """Retrying a client request must not inflate a learner's completion count."""
    with TestClient(app) as client:
        headers = learner_headers(client, "progress")
        run = create_course(client, headers)
        lesson = run["course"]["modules"][0]["lessons"][0]
        endpoint = f"/learning-runs/{run['id']}/progress"

        first = client.patch(endpoint, headers=headers, json={"lesson_id": lesson["id"], "completed": True})
        retry = client.patch(endpoint, headers=headers, json={"lesson_id": lesson["id"], "completed": True})
        reopened = client.patch(endpoint, headers=headers, json={"lesson_id": lesson["id"], "completed": False})

        assert first.status_code == retry.status_code == reopened.status_code == 200
        assert first.json()["completed_lessons"] == 1
        assert retry.json()["completed_lessons"] == 1
        assert reopened.json()["completed"] is False
        assert reopened.json()["completed_lessons"] == 0
