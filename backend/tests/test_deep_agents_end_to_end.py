"""Deterministic end-to-end proof of the browser/Deep Agents learning workflow."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.browser.client import AgentBrowserClient
from app.browser.gateway import BrowserGateway
from app.harness.deep_agents import DeepAgentExecution
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


def _write_fake_model(path: Path) -> None:
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
    requirements = [
        ('foundations', 'Which definitions and prerequisites ground Python functions?', 'core'),
        ('mechanism', 'How do Python functions bind inputs and return outputs?', 'core'),
        ('examples', 'Which worked examples reveal Python function behavior?', 'core'),
        ('boundaries', 'Which limitations and boundary cases constrain Python functions?', 'supporting'),
        ('integration', 'How do Python functions connect to wider program design?', 'core'),
    ]
    response = {
        'coverage_requirements': [
            {'id': identifier, 'question': question, 'priority': priority,
             'depth': 'detailed', 'evidence_policy': 'single_source_ok'}
            for identifier, question, priority in requirements
        ],
        'queries': [
            {'query': f'Python functions {identifier} authoritative guide',
             'purpose': f'Cover {identifier}', 'coverage_ids': [identifier]}
            for identifier, _question, _priority in requirements
        ],
        'seed_candidates': [
            {'title': sources[index]['title'], 'url': sources[index]['url'],
             'purpose': f'Canonical evidence for {identifier}',
             'coverage_ids': [identifier], 'kind': sources[index]['kind']}
            for index, (identifier, _question, _priority) in enumerate(requirements)
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
    requirement_ids = ['foundations', 'mechanism', 'examples', 'boundaries', 'integration']
    response = {
        'topic': request['learner_goal']['topic'],
        'sources': [
            {
                'title': page['title'], 'url': page['url'], 'kind': sources[index]['kind'],
                'rationale': f'Verified evidence for curriculum section {index}',
                'key_points': [f'Concrete mechanism supported by source {index}',
                               f'Worked example or limitation supported by source {index}'],
                'coverage_evidence': [{
                    'requirement_id': requirement_ids[int(page['url'].split('source-')[1])],
                    'support': 'strong'
                }],
            }
            for index, page in enumerate(pages)
        ],
    }
elif agent == 'ResearchCoverageEvaluator':
    requirements = request['context']['coverage_requirements']
    linked = {
        evidence['requirement_id']: source['url']
        for source in request['context']['sources']
        for evidence in source.get('coverage_evidence', [])
    }
    response = {
        'assessments': [
            {'requirement_id': item['id'],
             'status': 'covered' if item['id'] in linked else 'missing',
             'confidence': 0.98 if item['id'] in linked else 0,
             'supported_by': [linked[item['id']]] if item['id'] in linked else [],
             'rationale': f"Evidence for {item['id']} was evaluated."}
            for item in requirements
        ],
        'sufficient': len(linked) == len(requirements), 'reason': 'Coverage was evaluated.'
    }
elif agent == 'Planner':
    response = {'chapters': [{
        'title': 'Function foundations',
        'summary': 'Build a precise mental model of Python functions, then apply it to observable examples.',
        'sections': [
            {'title': 'Function inputs and outputs',
             'objective': 'Explain how parameters bind inputs and return values expose outputs.',
             'coverage_ids': ['foundations', 'mechanism', 'examples'],
             'key_points': [f'Concept teaching section {index}' for index in range(6)],
             'estimated_minutes': 60},
            {'title': 'Validate function behavior',
             'objective': 'Use representative and boundary examples to validate a function result.',
             'coverage_ids': ['boundaries', 'integration'],
             'key_points': [f'Validation teaching section {index}' for index in range(6)],
             'estimated_minutes': 60},
        ],
    }]}
elif agent == 'LessonWriter':
    draft = request['context']['lesson_draft']
    target_urls = {
        target['requirement_id']: target['supported_by'][0]
        for target in request['context']['coverage_targets']
    }
    coverage_ids = draft['coverage_ids']
    def paragraphs(label):
        items = []
        for paragraph_index in range(6):
            requirement_id = coverage_ids[paragraph_index % len(coverage_ids)]
            sentences = []
            for detail_index in range(7):
                sentences.append(
                    f'{label} paragraph {paragraph_index}, detail {detail_index}, explains a distinct function mechanism with '
                    f'a concrete input, an observable output, a prediction, a boundary condition, and a validation decision '
                    f'that helps the learner revise a precise mental model rather than memorize generic advice.'
                )
            items.append({'heading': f'{label} section {paragraph_index}',
                          'text': ' '.join(sentences),
                          'coverage_ids': [requirement_id],
                          'source_urls': [target_urls[requirement_id]]})
        return items
    response = {'lesson': {'id': draft['id'], 'paragraphs': paragraphs('LESSON_WRITER_CONTENT')}}
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


def test_fake_browser_and_deep_agent_generate_complete_course(tmp_path, monkeypatch):
    class FakeLiteLLMGateway:
        async def create_trace_key(self, **_kwargs):
            return "test-session-trace-key"

        async def spend_logs(self, _api_key):
            return []

    monkeypatch.setattr("app.harness.runtime.LiteLLMGateway", FakeLiteLLMGateway)
    fake_browser = tmp_path / "fake_agent_browser.py"
    fake_model = tmp_path / "fake_model.py"
    _write_fake_browser(fake_browser)
    _write_fake_model(fake_model)

    class FakeDeepAgentRuntime:
        async def execute(self, prompt, **_kwargs):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(fake_model),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate(prompt.encode())
            assert process.returncode == 0
            envelope = json.loads(stdout)
            return DeepAgentExecution(json.loads(envelope["response"]))

    gateway = BrowserGateway(
        client=AgentBrowserClient(command=[sys.executable, str(fake_browser)]),
        resolver=_public_resolver,
    )
    browser_result = asyncio.run(gateway.browser_read(["https://docs.example.com/source-0"]))
    assert browser_result["pages"][0]["status"] == "ok"

    monkeypatch.setattr("app.harness.runtime.DeepAgentRuntime", FakeDeepAgentRuntime)
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
            assert response.status_code == 202, response.text
            started = response.json()
            assert started["status"] == "running"
            # TestClient runs background tasks before returning the response.
            status = client.get(f"/learning-runs/{started['id']}/status", headers=learner).json()
            assert status == {"id": started["id"], "status": "completed", "error": None}
            course = client.get(f"/learning-runs/{started['id']}", headers=learner).json()
            assert len(course["research"]["sources"]) == 5
            assert len(course["research"]["visited_sources"]) == 5
            assert course["research"]["stop_reason"] == "coverage_satisfied"
            assert all(
                item["status"] == "covered" for item in course["research"]["coverage"]
            )
            assert course["course"]["modules"][0]["lessons"]
            assert course["course"]["modules"][0]["lessons"][0]["content"].startswith(
                "LESSON_WRITER_CONTENT"
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
            assert course.get("assessment") is None  # generated by a later assessment step
            assert set(course["sessions"]) == {
                "Researcher", "Planner",
                "LessonWriter:chapter-1-section-1",
                "LessonWriter:chapter-1-section-2",
            }
            module = course["course"]["modules"][0]
            assert module["title"] == "Function foundations"
            assert [lesson["title"] for lesson in module["lessons"]] == [
                "Function inputs and outputs", "Validate function behavior",
            ]

            saved = client.get(f"/learning-runs/{course['id']}", headers=learner)
            assert saved.status_code == 200, saved.text
            saved_course = saved.json()
            assert saved_course["course"]["modules"][0]["lessons"] == course["course"]["modules"][0]["lessons"]
            assert len(saved_course["research"]["sources"]) == 5

            trace = client.get(f"/learning-runs/{course['id']}/trace", headers=learner)
            assert trace.status_code == 200, trace.text
            trace_body = trace.json()
            session_names = {session["agent_name"] for session in trace_body["sessions"]}
            assert {
                "BrowserResearch", "ResearchQueryPlanner", "ResearchSelector",
                "ResearchSynthesisPart1", "ResearchCoverageRound1", "Planner",
                "LessonWriter",
            } <= session_names
            assert all(session["transcript"] for session in trace_body["sessions"])
            researcher_trace = next(
                session for session in trace_body["sessions"]
                if session["agent_name"] == "BrowserResearch"
            )
            assert len(researcher_trace["tool_invocations"]) == 3
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

            quiz = client.post(
                f"/learning-runs/{course['id']}/quiz-submissions",
                headers=learner,
                json={"quiz_id": "course-quiz", "answers": [{"question_id": "q1", "answer": "a"}]},
            )
            assert quiz.status_code == 422 and "no quiz yet" in quiz.json()["detail"]

            submission = client.post(
                f"/learning-runs/{course['id']}/submissions",
                headers=learner,
                json={
                    "kind": "assignment",
                    "response": "I implemented both functions, recorded boundary predictions and outputs, then revised input validation based on the observed evidence.",
                },
            )
            assert submission.status_code == 409 and "no assignment yet" in submission.json()["detail"]

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
            assert admin
