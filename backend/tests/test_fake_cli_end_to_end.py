"""Deterministic executable-level proof of the browser/Gemini learning workflow."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.browser.client import AgentBrowserClient
from app.browser.gateway import BrowserGateway
from app.main import app
from app.services.learning_service import learning_service


def _public_resolver(_host, port, *, type):
    return [(2, type, 6, "", ("93.184.216.34", port))]


def _write_fake_browser(path: Path) -> None:
    path.write_text(
        """import json, sys
commands = json.loads(sys.stdin.read())
opened = next((item[1] for item in commands if item[0] == 'open'), 'https://docs.example.com/source-0')
results = []
for item in commands:
    if item[:2] == ['get', 'url']:
        result = {'origin': opened, 'url': opened}
    elif item[:2] == ['get', 'title']:
        result = {'title': 'Verified source'}
    elif item[:3] == ['get', 'text', 'body']:
        result = {'content': 'A bounded, browser-rendered source body.'}
    elif item[0] == 'close':
        result = {'closed': True}
    else:
        result = {}
    results.append({'success': True, 'result': result})
print(json.dumps(results))
""",
        encoding="utf-8",
    )


def _write_fake_gemini(path: Path) -> None:
    path.write_text(
        """import json, sys
prompt = sys.stdin.read() or sys.argv[-1]
request = json.loads(prompt)
agent = request.get('agent')
sources = [
    {'title': f'Source {index}', 'url': f'https://docs.example.com/source-{index}',
     'kind': ['documentation', 'paper', 'book', 'lecture', 'slides', 'article', 'repository'][index % 7],
     'rationale': f'Verified evidence for curriculum section {index}',
     'key_points': [f'Concrete mechanism supported by source {index}',
                    f'Worked example or limitation supported by source {index}']}
    for index in range(12)
]
if agent == 'ResearchQueryPlanner':
    response = {
        'coverage_requirements': [{
            'id': 'core', 'question': 'How do Python functions bind inputs and return outputs?',
            'priority': 'core', 'depth': 'detailed', 'evidence_policy': 'single_source_ok'
        }],
        'queries': [
            {'query': 'Python functions authoritative guide', 'purpose': 'Cover the core mechanism', 'coverage_ids': ['core']}
        ],
        'seed_candidates': [
            {'title': sources[0]['title'], 'url': sources[0]['url'], 'purpose': 'Canonical Python function documentation',
             'coverage_ids': ['core'], 'kind': 'documentation'}
        ],
    }
elif agent == 'ResearchSelector':
    candidates = request['context']['candidates']
    response = {'selections': [
        {'url': item['url'], 'kind': sources[index]['kind'], 'reason': f'Coverage reason {index}'}
        for index, item in enumerate(candidates[:request['context']['max_selections']])
    ]}
elif agent == 'ResearchSynthesis':
    pages = request['context']['pages']
    response = {
        'topic': request['learner_goal']['topic'],
        'sources': [
            {
                'title': page['title'], 'url': page['url'], 'kind': sources[index]['kind'],
                'rationale': f'Verified evidence for curriculum section {index}',
                'key_points': [f'Concrete mechanism supported by source {index}',
                               f'Worked example or limitation supported by source {index}'],
                'coverage_evidence': [{'requirement_id': 'core', 'support': 'strong'}],
            }
            for index, page in enumerate(pages)
        ],
    }
elif agent == 'ResearchCoverageEvaluator':
    source = request['context']['sources'][0]
    response = {
        'assessments': [{
            'requirement_id': 'core', 'status': 'covered', 'confidence': 0.98,
            'supported_by': [source['url']], 'rationale': 'The documentation covers the core mechanism.'
        }],
        'sufficient': True, 'reason': 'All requirements are covered.'
    }
elif agent == 'Planner':
    def paragraphs(label, first_source):
        items = []
        for paragraph_index in range(6):
            sentences = []
            for detail_index in range(7):
                sentences.append(
                    f'{label} paragraph {paragraph_index}, detail {detail_index}, explains a distinct function mechanism with '
                    f'a concrete input, an observable output, a prediction, a boundary condition, and a validation decision '
                    f'that helps the learner revise a precise mental model rather than memorize generic advice.'
                )
            items.append({'text': ' '.join(sentences),
                          'source_urls': [sources[0]['url']]})
        return items
    curriculum = [{'week': 1, 'title': 'Function foundations',
                   'outcomes': ['Define and call a function', 'Validate a result'],
                   'source_urls': [sources[0]['url']],
                   'overview': 'Build a precise mental model of Python functions, then apply it to observable examples.',
                   'estimated_hours': 3,
                   'lessons': [
                     {'id': 'provider-functions-concepts', 'title': 'Function inputs and outputs',
                      'objective': 'Explain how parameters bind inputs and return values expose outputs.',
                      'paragraphs': paragraphs('PROVIDER_AUTHORED_CONTENT', 0),
                      'practice': 'Implement double and three related functions, then record inputs, predicted outputs, and actual outputs.',
                      'estimated_minutes': 60, 'source_urls': [sources[0]['url']]},
                     {'id': 'provider-functions-validation', 'title': 'Validate function behavior',
                      'objective': 'Use representative and boundary examples to validate a function result.',
                      'paragraphs': paragraphs('PROVIDER_VALIDATION_CONTENT', 1),
                      'practice': 'Write three executable checks for one function and explain what each check demonstrates about its contract.',
                      'estimated_minutes': 60, 'source_urls': [sources[0]['url']]}
                   ]}]
    assessment = {
        'quiz_items': [
            {'id': 'week-1-q1', 'module_week': 1,
             'prompt': 'What observable behavior distinguishes returning a value from printing it?',
             'choices': ['The caller receives the returned value', 'Both always change global state', 'Printing creates a parameter'],
             'correct_answer': 'The caller receives the returned value',
             'explanation': 'A return expression passes a value to the caller, while printing only writes text to an output stream.'},
            {'id': 'week-1-q2', 'module_week': 1,
             'prompt': 'Which test best checks a function contract at a boundary?',
             'choices': ['Use the smallest valid input and compare the exact result', 'Rename the function', 'Skip invalid inputs'],
             'correct_answer': 'Use the smallest valid input and compare the exact result',
             'explanation': 'A boundary example tests the edge of the stated contract and compares an observable result with an expectation.'},
        ],
        'assignment': {
            'title': 'Function contract evidence notebook',
            'prompt': 'Implement two related Python functions and document their contracts, boundary examples, observed results, and one evidence-based revision.',
            'deliverables': ['Two executable function implementations', 'A table of predicted and observed results'],
            'rubric': ['Function contracts are stated precisely', 'Recorded evidence supports every claimed result'],
        },
        'project': 'Build a small reusable Python module, validate its public function contracts, and explain the evidence behind each design decision.',
    }
    response = {'curriculum': curriculum, 'assessment': assessment}
else:
    raise SystemExit(f'Unexpected agent role: {agent}')
print(json.dumps({'response': json.dumps(response)}))
""",
        encoding="utf-8",
    )


def _headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_fake_browser_and_gemini_executables_generate_complete_course(tmp_path, monkeypatch):
    class FakeLiteLLMGateway:
        async def create_trace_key(self, **_kwargs):
            return "test-session-trace-key"

        async def spend_logs(self, _api_key):
            return []

    monkeypatch.setattr("app.harness.runtime.LiteLLMGateway", FakeLiteLLMGateway)
    fake_browser = tmp_path / "fake_agent_browser.py"
    fake_gemini = tmp_path / "fake_gemini.py"
    _write_fake_browser(fake_browser)
    _write_fake_gemini(fake_gemini)

    gateway = BrowserGateway(
        client=AgentBrowserClient(command=[sys.executable, str(fake_browser)]),
        resolver=_public_resolver,
    )
    browser_result = asyncio.run(gateway.browser_read(["https://docs.example.com/source-0"]))
    assert browser_result["pages"][0]["status"] == "ok"

    monkeypatch.setenv("GEMINI_CLI_COMMAND", f'"{sys.executable}" "{fake_gemini}"')
    monkeypatch.setattr(
        learning_service,
        "browser_gateway_factory",
        lambda: BrowserGateway(
            client=AgentBrowserClient(command=[sys.executable, str(fake_browser)]),
            resolver=_public_resolver,
        ),
    )
    with TestClient(app) as client:
        admin = _headers(client, "admin@example.com", "AdminPass123!")
        harness = client.put(
            "/analytics/settings/agent-harness",
            headers=admin,
            json={"harness": "gemini-cli"},
        )
        assert harness.status_code == 200, harness.text
        try:
            email = f"fake-cli-{uuid4().hex}@example.com"
            registration = client.post(
                "/auth/register", json={"email": email, "password": "LearnerPass123!"}
            )
            learner = {"Authorization": f"Bearer {registration.json()['access_token']}"}
            response = client.post(
                "/learning-runs",
                headers=learner,
                json={"topic": "Python functions", "weeks": 1, "hours_per_week": 3},
            )
            assert response.status_code == 200, response.text
            course = response.json()
            assert len(course["research"]["sources"]) == 1
            assert len(course["research"]["visited_sources"]) == 1
            assert course["research"]["stop_reason"] == "coverage_satisfied"
            assert course["research"]["coverage"][0]["status"] == "covered"
            assert course["course"]["modules"][0]["lessons"]
            assert course["course"]["modules"][0]["lessons"][0]["content"].startswith(
                "PROVIDER_AUTHORED_CONTENT"
            )
            assert len(course["course"]["modules"][0]["lessons"][0]["paragraphs"]) == 6
            assert all(
                paragraph["source_urls"]
                for lesson in course["course"]["modules"][0]["lessons"]
                for paragraph in lesson["paragraphs"]
            )
            verified_urls = {source["url"] for source in course["research"]["sources"]}
            assert set(course["course"]["modules"][0]["source_urls"]) <= verified_urls
            assert all(
                set(lesson["source_urls"]) <= verified_urls
                for lesson in course["course"]["modules"][0]["lessons"]
            )
            assert course["assessment"]["quiz_items"]
            assert course["assessment"]["assignment"]["deliverables"]
            assert set(course["sessions"]) == {"Researcher", "Planner"}
            assert all(
                "correct_answer" not in question and "explanation" not in question
                for question in course["assessment"]["quiz_items"]
            )

            saved = client.get(f"/learning-runs/{course['id']}", headers=learner)
            assert saved.status_code == 200, saved.text
            saved_course = saved.json()
            assert saved_course["course"]["modules"][0]["lessons"] == course["course"]["modules"][0]["lessons"]
            assert len(saved_course["research"]["sources"]) == 1

            trace = client.get(f"/learning-runs/{course['id']}/trace", headers=learner)
            assert trace.status_code == 200, trace.text
            trace_body = trace.json()
            assert {session["agent_name"] for session in trace_body["sessions"]} == {
                "BrowserResearch", "ResearchQueryPlanner", "ResearchSelector",
                "ResearchSynthesisPart1", "ResearchCoverageRound1", "Planner",
            }
            assert all(session["transcript"] for session in trace_body["sessions"])
            researcher_trace = next(
                session for session in trace_body["sessions"]
                if session["agent_name"] == "BrowserResearch"
            )
            assert len(researcher_trace["tool_invocations"]) == 1
            assert {
                page["url"]
                for tool in researcher_trace["tool_invocations"]
                for page in tool["metadata"].get("page_results", [])
            } == verified_urls

            lesson = course["course"]["modules"][0]["lessons"][0]
            progress = client.patch(
                f"/learning-runs/{course['id']}/progress",
                headers=learner,
                json={"lesson_id": lesson["id"], "completed": True},
            )
            assert progress.status_code == 200, progress.text
            assert progress.json()["completed_lessons"] == 1

            answers = [
                {"question_id": question["id"], "answer": question["choices"][0]}
                for question in course["assessment"]["quiz_items"]
            ]
            quiz = client.post(
                f"/learning-runs/{course['id']}/quiz-submissions",
                headers=learner,
                json={"quiz_id": "course-quiz", "answers": answers},
            )
            assert quiz.status_code == 200, quiz.text
            assert quiz.json()["score_percent"] == 100

            submission = client.post(
                f"/learning-runs/{course['id']}/submissions",
                headers=learner,
                json={
                    "kind": "assignment",
                    "response": "I implemented both functions, recorded boundary predictions and outputs, then revised input validation based on the observed evidence.",
                },
            )
            assert submission.status_code == 200, submission.text
            assert submission.json()["feedback"]

            repeated_progress = client.patch(
                f"/learning-runs/{course['id']}/progress",
                headers=learner,
                json={"lesson_id": lesson["id"], "completed": True},
            )
            reopened_progress = client.patch(
                f"/learning-runs/{course['id']}/progress",
                headers=learner,
                json={"lesson_id": lesson["id"], "completed": False},
            )
            assert repeated_progress.json()["completed_lessons"] == 1
            assert reopened_progress.json()["completed_lessons"] == 0

            other_email = f"other-{uuid4().hex}@example.com"
            other_registration = client.post(
                "/auth/register",
                json={"email": other_email, "password": "LearnerPass123!"},
            )
            other = {
                "Authorization": f"Bearer {other_registration.json()['access_token']}"
            }
            assert client.get(
                f"/learning-runs/{course['id']}/trace", headers=other
            ).status_code == 404
            assert client.patch(
                f"/learning-runs/{course['id']}/progress",
                headers=other,
                json={"lesson_id": lesson["id"], "completed": True},
            ).status_code == 404
        finally:
            reset = client.put(
                "/analytics/settings/agent-harness", headers=admin, json={"harness": "gemini-cli"}
            )
            assert reset.status_code == 200, reset.text
