import pytest

from app.schemas.learning import LearningGoal, ResearchBrief, Source
from app.services.learning_service import LearningService


def _research() -> ResearchBrief:
    kinds = ("documentation", "paper", "book", "lecture", "article", "repository")
    return ResearchBrief(
        topic="Python functions",
        sources=[
            Source(
                title=f"Verified source {index}",
                url=f"https://docs.example.com/source-{index}",
                kind=kinds[index % len(kinds)],
                rationale=f"Supports the progressive lesson section numbered {index}.",
            )
            for index in range(8)
        ],
    )


def _lesson(identifier: str, *, source_urls: list[str] | None = None) -> dict:
    return {
        "id": identifier,
        "title": f"Lesson {identifier}",
        "objective": "Explain a concrete mechanism and validate its observable result.",
        "content": (
            f"PROVIDER CONTENT {identifier}: This is an intentionally specific explanation of function parameters, "
            "local bindings, return values, and caller-visible results. It traces a worked example from an input through "
            "the function body to an output, then explains a limitation and how a boundary check exposes it. "
        ) * 8,
        "practice": "Implement the worked example, change one input, predict the result, and compare it with the output.",
        "estimated_minutes": 45,
        **({"source_urls": source_urls} if source_urls is not None else {}),
    }


def _planner_output(*, module_urls: list[str] | None = None, lessons: list[dict] | None = None) -> dict:
    return {
        "curriculum": [
            {
                "week": 1,
                "title": "Function foundations",
                "outcomes": [
                    "Trace parameter binding through a function call",
                    "Validate a return value against a stated expectation",
                ],
                "source_urls": module_urls or ["https://docs.example.com/source-0"],
                "overview": "Build a precise function model through a worked example and evidence-backed practice.",
                "estimated_hours": 2,
                "lessons": lessons if lessons is not None else [_lesson("one"), _lesson("two")],
            }
        ]
    }


def test_provider_course_preserves_authored_content_and_normalizes_verified_citations():
    research = _research()
    output = _planner_output(
        module_urls=["HTTPS://DOCS.EXAMPLE.COM/source-0#section"],
        lessons=[
            _lesson("one"),
            _lesson("two", source_urls=["https://docs.example.com/source-1#example"]),
        ],
    )

    curriculum = LearningService._provider_curriculum(
        LearningGoal(topic="Python functions", weeks=1, hours_per_week=3),
        output,
        research,
    )

    module = curriculum[0]
    assert module.source_urls == ["https://docs.example.com/source-0"]
    assert module.lessons[0].content.startswith("PROVIDER CONTENT one")
    assert module.lessons[0].source_urls == module.source_urls
    assert module.lessons[1].source_urls == ["https://docs.example.com/source-1"]


def test_provider_course_rejects_any_unverified_module_or_lesson_citation():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)
    research = _research()

    with pytest.raises(ValueError, match="unverified source URL in module week 1"):
        LearningService._provider_curriculum(
            goal,
            _planner_output(module_urls=["https://unverified.example.com/source"]),
            research,
        )

    with pytest.raises(ValueError, match="unverified source URL in lesson two"):
        LearningService._provider_curriculum(
            goal,
            _planner_output(
                lessons=[
                    _lesson("one"),
                    _lesson("two", source_urls=["https://unverified.example.com/source"]),
                ]
            ),
            research,
        )


def test_provider_course_rejects_incomplete_content_instead_of_inserting_generic_lessons():
    with pytest.raises(ValueError, match="at least two complete lessons"):
        LearningService._provider_curriculum(
            LearningGoal(topic="Python functions", weeks=1, hours_per_week=3),
            _planner_output(lessons=[]),
            _research(),
        )


def test_provider_course_requires_exact_requested_progression_and_weekly_budget():
    research = _research()
    goal = LearningGoal(topic="Python functions", weeks=2, hours_per_week=1)

    with pytest.raises(ValueError, match="exactly one module for each week"):
        LearningService._provider_curriculum(goal, _planner_output(), research)

    with pytest.raises(ValueError, match="weekly-hour budget"):
        LearningService._provider_curriculum(
            LearningGoal(topic="Python functions", weeks=1, hours_per_week=1),
            _planner_output(),
            research,
        )


def test_provider_modules_require_primary_evidence_and_bounded_lesson_time():
    research = _research()
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)

    with pytest.raises(ValueError, match="must cite a verified primary source"):
        LearningService._provider_curriculum(
            goal,
            _planner_output(module_urls=["https://docs.example.com/source-3"]),
            research,
        )

    long_lessons = [_lesson("one"), _lesson("two")]
    for lesson in long_lessons:
        lesson["estimated_minutes"] = 100
    with pytest.raises(ValueError, match="lesson time exceeds"):
        LearningService._provider_curriculum(
            goal,
            _planner_output(lessons=long_lessons),
            research,
        )
