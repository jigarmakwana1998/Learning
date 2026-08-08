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
prompt = sys.argv[-1]
sources = [
    {'title': f'Source {index}', 'url': f'https://docs.example.com/source-{index}',
     'kind': ['documentation', 'paper', 'book', 'lecture', 'article', 'repository'][index % 6],
     'rationale': f'Verified evidence for curriculum section {index}'}
    for index in range(8)
]
if '\"agent\": \"Researcher\"' in prompt:
    print(json.dumps({'type': 'tool_use', 'tool_id': 'read-1', 'tool_name': 'browser_read',
                      'parameters': {'urls': [item['url'] for item in sources]}}))
    print(json.dumps({'type': 'tool_result', 'tool_id': 'read-1', 'tool_name': 'browser_read',
                      'status': 'success',
                      'output': {'pages': [{'status': 'ok', 'url': item['url']} for item in sources]}}))
    print(json.dumps({'type': 'result', 'response': json.dumps({'topic': 'Python functions', 'sources': sources})}))
elif '\"agent\": \"Planner\"' in prompt:
    concepts = ('PROVIDER_AUTHORED_CONTENT: A Python function creates a named unit of behavior. Parameters bind each supplied '
                'argument to a local name, the body transforms those values, and return sends a result back to the caller. '
                'A worked example traces def double(value): return value * 2 and compares double(3) with its observable result, '
                '6. The caller owns the returned value, while names created inside the body remain local. A useful validation '
                'loop predicts an output, runs one representative input, and explains any mismatch before adding a boundary case. ' * 4)
    validation = ('PROVIDER_VALIDATION_CONTENT: Validation compares a stated expectation with an observed return value. Start '
                  'with a representative input, add a boundary value, and then test an invalid value where the function contract '
                  'defines an error. Keep one variable changing at a time so a mismatch points to a specific assumption. Record '
                  'the call, expected result, actual result, and explanation. This evidence distinguishes a real behavioral check '
                  'from a plausible-looking output and makes later revisions deliberate. ' * 5)
    curriculum = [{'week': 1, 'title': 'Function foundations',
                   'outcomes': ['Define and call a function', 'Validate a result'],
                   'source_urls': [sources[0]['url'], sources[1]['url']],
                   'overview': 'Build a precise mental model of Python functions, then apply it to observable examples.',
                   'estimated_hours': 3,
                   'lessons': [
                     {'id': 'provider-functions-concepts', 'title': 'Function inputs and outputs',
                      'objective': 'Explain how parameters bind inputs and return values expose outputs.',
                      'content': concepts,
                      'practice': 'Implement double and three related functions, then record inputs, predicted outputs, and actual outputs.',
                      'estimated_minutes': 60, 'source_urls': [sources[0]['url']]},
                     {'id': 'provider-functions-validation', 'title': 'Validate function behavior',
                      'objective': 'Use representative and boundary examples to validate a function result.',
                      'content': validation,
                      'practice': 'Write three executable checks for one function and explain what each check demonstrates about its contract.',
                      'estimated_minutes': 60, 'source_urls': [sources[1]['url']]}
                   ]}]
    print(json.dumps({'response': json.dumps({'curriculum': curriculum})}))
else:
    print(json.dumps({'response': json.dumps({'quiz': [], 'assignment': {}, 'project': 'Practice project'})}))
""",
        encoding="utf-8",
    )


def _headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_fake_browser_and_gemini_executables_generate_complete_course(tmp_path, monkeypatch):
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
    with TestClient(app) as client:
        admin = _headers(client, "admin@example.com", "AdminPass123!")
        provider = client.put(
            "/analytics/settings/agent-provider",
            headers=admin,
            json={"provider": "gemini-cli"},
        )
        assert provider.status_code == 200, provider.text
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
            assert len(course["research"]["sources"]) == 8
            assert course["course"]["modules"][0]["lessons"]
            assert course["course"]["modules"][0]["lessons"][0]["content"].startswith(
                "PROVIDER_AUTHORED_CONTENT"
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
            assert len(saved_course["research"]["sources"]) == 8
        finally:
            reset = client.put(
                "/analytics/settings/agent-provider", headers=admin, json={"provider": "mock"}
            )
            assert reset.status_code == 200, reset.text
