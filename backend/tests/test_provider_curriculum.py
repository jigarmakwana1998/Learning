import pytest

from app.schemas.learning import LearningGoal, ResearchBrief, ResearchCoverage, Source
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
                key_points=[
                    f"Explains the concrete mechanism used in section {index}.",
                    f"Provides a worked example or limitation for section {index}.",
                ],
            )
            for index in range(8)
        ],
    )


def _lesson(identifier: str, *, source_urls: list[str] | None = None) -> dict:
    paragraphs = [
        {
            "heading": f"Distinct teaching section {index}",
            "text": (
                f"Paragraph {index} for {identifier} develops a distinct part of the function model. "
                f"Mechanism {index} explains how Python binds an argument to a parameter, evaluates expressions inside local "
                f"scope, and returns an observable value to the caller in example {index}. A worked example for case {index} "
                f"follows one input through the function body, compares the predicted result with the actual result, and "
                f"identifies the exact assumption that boundary case {index} can test. The explanation distinguishes local "
                f"names from caller-owned values and shows why return is different from printing for scenario {index}. It then "
                f"connects that mechanism to a practical debugging decision, including what evidence to record when result "
                f"{index} differs from the prediction. A limitation specific to example {index} shows how invalid inputs can "
                f"violate the function contract and why a deliberate error is preferable to a misleading result. Finally, the "
                f"paragraph gives a validation checkpoint for mechanism {index} so the learner can explain the behavior without "
                f"copying syntax. The learner then changes one variable in scenario {index}, predicts the consequence, and "
                f"uses the observed value to revise the mental model. This makes paragraph {index} a separate teaching unit "
                f"rather than repeated filler. A final comparison for scenario {index} contrasts the expected control flow "
                f"with a nearby alternative, explains which observation would distinguish them, and connects that evidence "
                f"back to the function contract the learner is testing."
            ),
            "source_urls": [
                f"https://docs.example.com/source-{index % 2}",
            ],
        }
        for index in range(6)
    ]
    return {
        "id": identifier,
        "title": f"Lesson {identifier}",
        "objective": "Explain a concrete mechanism and validate its observable result.",
        "section_plan": [f"Develop distinct function concept {index}" for index in range(6)],
        "paragraphs": paragraphs,
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


def _covered_research() -> ResearchBrief:
    research = _research()
    return research.model_copy(
        update={
            "coverage": [
                ResearchCoverage(
                    requirement_id="foundations",
                    question="Which function concepts form the foundation?",
                    priority="core",
                    depth="detailed",
                    evidence_policy="single_source_ok",
                    status="covered",
                    confidence=0.95,
                    supported_by=["https://docs.example.com/source-0"],
                    rationale="The source supplies detailed foundation evidence.",
                ),
                ResearchCoverage(
                    requirement_id="mechanism",
                    question="How does parameter binding and return work?",
                    priority="core",
                    depth="detailed",
                    evidence_policy="single_source_ok",
                    status="covered",
                    confidence=0.95,
                    supported_by=["https://docs.example.com/source-1"],
                    rationale="The source supplies detailed mechanism evidence.",
                ),
            ],
            "stop_reason": "coverage_satisfied",
        }
    )


def _traced_lesson(identifier: str, coverage_id: str, source_url: str) -> dict:
    lesson = _lesson(identifier, source_urls=[source_url])
    lesson["coverage_ids"] = [coverage_id]
    for paragraph in lesson["paragraphs"]:
        paragraph["coverage_ids"] = [coverage_id]
        paragraph["source_urls"] = [source_url]
    return lesson


def test_provider_course_preserves_authored_content_and_derives_chapter_sources():
    research = _research()
    output = _planner_output(
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
    # A chapter's sources are exactly what its sections cite, normalized.
    assert module.source_urls == [
        "https://docs.example.com/source-0",
        "https://docs.example.com/source-1",
    ]
    assert module.lessons[0].content.startswith("Paragraph 0 for one")
    assert module.lessons[1].source_urls == [
        "https://docs.example.com/source-1",
        "https://docs.example.com/source-0",
    ]


def test_provider_course_rejects_unverified_lesson_citations_and_empty_chapters():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)
    research = _research()

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

    with pytest.raises(ValueError, match="at least one section"):
        LearningService._provider_curriculum(goal, _planner_output(lessons=[]), research)


def test_provider_curriculum_proves_every_research_requirement_reaches_cited_lessons():
    output = _planner_output(
        module_urls=[
            "https://docs.example.com/source-0",
            "https://docs.example.com/source-1",
        ],
        lessons=[
            _traced_lesson("one", "foundations", "https://docs.example.com/source-0"),
            _traced_lesson("two", "mechanism", "https://docs.example.com/source-1"),
        ],
    )
    output["curriculum"][0]["coverage_ids"] = ["foundations", "mechanism"]

    modules = LearningService._provider_curriculum(
        LearningGoal(topic="Python functions", weeks=1, hours_per_week=3),
        output,
        _covered_research(),
    )

    assert modules[0].coverage_ids == ["foundations", "mechanism"]
    assert {
        requirement_id
        for lesson in modules[0].lessons
        for requirement_id in lesson.coverage_ids
    } == {"foundations", "mechanism"}


def test_provider_curriculum_rejects_unmapped_or_unsupported_coverage_claims():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)
    research = _covered_research()
    lessons = [
        _traced_lesson("one", "foundations", "https://docs.example.com/source-0"),
        _traced_lesson("two", "foundations", "https://docs.example.com/source-0"),
    ]
    missing = _planner_output(lessons=lessons)
    missing["curriculum"][0]["coverage_ids"] = ["foundations"]
    with pytest.raises(ValueError, match="does not cover every verified research requirement"):
        LearningService._provider_curriculum(goal, missing, research)

    unsupported_lessons = [
        _traced_lesson("one", "foundations", "https://docs.example.com/source-1"),
        _traced_lesson("two", "mechanism", "https://docs.example.com/source-1"),
    ]
    unsupported = _planner_output(lessons=unsupported_lessons)
    unsupported["curriculum"][0]["coverage_ids"] = ["foundations", "mechanism"]
    with pytest.raises(ValueError, match="does not cite evidence supporting coverage requirement foundations"):
        LearningService._provider_curriculum(goal, unsupported, research)


def test_course_generation_gate_rejects_partial_research():
    research = _covered_research()
    research.coverage[1].status = "partial"
    research.stop_reason = "budget_exhausted"

    with pytest.raises(ValueError, match="course generation stopped before writing lessons"):
        LearningService._require_complete_research(research)


def _section(coverage_ids: list[str], *, minutes: int = 45, points: int = 6) -> dict:
    return {
        "title": f"Section on {' and '.join(coverage_ids)}",
        "objective": f"Explain {' and '.join(coverage_ids)} with a worked example.",
        "coverage_ids": coverage_ids,
        "key_points": [f"Distinct point {index} about {coverage_ids[0]}" for index in range(points)],
        "estimated_minutes": minutes,
    }


def _chapters(*sections_per_chapter: list[dict]) -> dict:
    return {
        "chapters": [
            {
                "title": f"Chapter {index}",
                "summary": f"Chapter {index} builds one coherent part of the function model.",
                "sections": sections,
            }
            for index, sections in enumerate(sections_per_chapter, start=1)
        ]
    }


def test_planner_chapters_become_modules_and_sections_become_lesson_drafts():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)
    plan = _chapters([_section(["foundations"])], [_section(["mechanism"], minutes=60), _section(["mechanism"])])

    modules = LearningService._planned_modules(goal, plan, _covered_research())

    assert [module["week"] for module in modules] == [1, 2]
    assert [module["title"] for module in modules] == ["Chapter 1", "Chapter 2"]
    second = modules[1]
    assert [lesson["id"] for lesson in second["lessons"]] == ["chapter-2-section-1", "chapter-2-section-2"]
    assert second["coverage_ids"] == ["mechanism"]
    assert second["estimated_hours"] == 2  # 105 minutes rounds up
    lesson = second["lessons"][0]
    assert lesson["section_plan"] == plan["chapters"][1]["sections"][0]["key_points"]
    assert lesson["paragraphs"] == [] and "practice" not in lesson


def test_planner_rejects_unknown_or_unassigned_coverage():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)
    research = _covered_research()

    with pytest.raises(ValueError, match="research did not cover: invented"):
        LearningService._planned_modules(goal, _chapters([_section(["foundations", "invented"])]), research)
    with pytest.raises(ValueError, match="without a section: mechanism"):
        LearningService._planned_modules(goal, _chapters([_section(["foundations"])]), research)


def test_planner_needs_distinct_key_points_and_fits_the_course_budget():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=1)
    research = _covered_research()

    with pytest.raises(ValueError, match="5-7 distinct key points"):
        LearningService._planned_modules(
            goal, _chapters([_section(["foundations"], points=3), _section(["mechanism"])]), research
        )
    with pytest.raises(ValueError, match="over the learner's 60-minute budget"):
        LearningService._planned_modules(
            goal, _chapters([_section(["foundations"]), _section(["mechanism"])]), research
        )


def test_planner_rejects_the_old_curriculum_and_assessment_payload():
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)

    with pytest.raises(ValueError, match="invalid chapter structure"):
        LearningService._planned_modules(goal, {"curriculum": [], "assessment": {}}, _covered_research())
