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


def _assessment_output() -> dict:
    return {
        "assessment": {
            "quiz_items": [
                {
                    "id": "week-1-q1",
                    "module_week": 1,
                    "prompt": "What does a Python function return to its caller?",
                    "choices": ["The evaluated return value", "Only printed text", "A new global variable"],
                    "correct_answer": "The evaluated return value",
                    "explanation": "The return statement passes an evaluated value back to the calling expression.",
                },
                {
                    "id": "week-1-q2",
                    "module_week": 1,
                    "prompt": "Which observation best validates a function boundary case?",
                    "choices": ["The exact result for the smallest valid input", "The function name", "The file size"],
                    "correct_answer": "The exact result for the smallest valid input",
                    "explanation": "Comparing a boundary input's observed result with its expected result tests the stated contract.",
                },
            ],
            "assignment": {
                "title": "Function contract notebook",
                "prompt": "Implement two functions and document their inputs, outputs, boundary cases, observed evidence, and one revision.",
                "deliverables": ["Two executable function implementations", "A table of predicted and observed outputs"],
                "rubric": ["Each function contract is precise", "Observed evidence supports every conclusion"],
            },
            "project": "Build a reusable Python module and validate each public function contract with recorded boundary evidence.",
        }
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
    assert module.lessons[0].content.startswith("Paragraph 0 for one")
    assert module.lessons[0].source_urls == [
        "https://docs.example.com/source-0",
        "https://docs.example.com/source-1",
    ]
    assert module.lessons[1].source_urls == [
        "https://docs.example.com/source-1",
        "https://docs.example.com/source-0",
    ]


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


def test_provider_modules_allow_the_relevant_verified_source_and_bound_lesson_time():
    research = _research()
    goal = LearningGoal(topic="Python functions", weeks=1, hours_per_week=3)

    modules = LearningService._provider_curriculum(
        goal,
        _planner_output(module_urls=["https://docs.example.com/source-3"]),
        research,
    )
    assert modules[0].source_urls == ["https://docs.example.com/source-3"]

    long_lessons = [_lesson("one"), _lesson("two")]
    for lesson in long_lessons:
        lesson["estimated_minutes"] = 100
    with pytest.raises(ValueError, match="lesson time exceeds"):
        LearningService._provider_curriculum(
            goal,
            _planner_output(lessons=long_lessons),
            research,
        )


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


def test_provider_assessment_preserves_authored_quiz_assignment_and_answer_keys():
    assessment = LearningService._provider_assessment(
        LearningGoal(topic="Python functions", weeks=1),
        _assessment_output(),
    )

    assert len(assessment.quiz_items) == 2
    assert assessment.quiz == assessment.quiz_items
    assert assessment.quiz_items[0].correct_answer == "The evaluated return value"
    assert assessment.assignment.title == "Function contract notebook"
    assert assessment.project.startswith("Build a reusable Python module")


def test_provider_assessment_normalizes_labeled_rubric_object():
    output = _assessment_output()
    output["assessment"]["assignment"]["rubric"] = {
        "Accuracy": "Every conclusion matches the recorded evidence",
        "Completeness": "Every required artifact is present",
    }
    output["assessment"]["project"] = {
        "title": "Function behavior capstone",
        "description": "Build and validate a reusable module with documented evidence",
    }

    assessment = LearningService._provider_assessment(
        LearningGoal(topic="Python functions", weeks=1), output
    )

    assert assessment.assignment.rubric == [
        "Accuracy: Every conclusion matches the recorded evidence",
        "Completeness: Every required artifact is present",
    ]
    assert assessment.project == (
        "Function behavior capstone. Build and validate a reusable module with documented evidence."
    )


def test_provider_assessment_rejects_missing_or_generic_content():
    goal = LearningGoal(topic="Python functions", weeks=1)

    with pytest.raises(ValueError, match="assessment object"):
        LearningService._provider_assessment(goal, {})

    invalid = _assessment_output()
    invalid["assessment"]["quiz_items"][0]["correct_answer"] = "Invented choice"
    with pytest.raises(ValueError, match="correct_answer in choices"):
        LearningService._provider_assessment(goal, invalid)

    too_few = _assessment_output()
    too_few["assessment"]["quiz_items"] = too_few["assessment"]["quiz_items"][:1]
    with pytest.raises(ValueError, match="2-5 quiz questions per week"):
        LearningService._provider_assessment(goal, too_few)
