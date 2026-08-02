"""Deterministic executable-level proof of the browser/Gemini learning workflow."""

from __future__ import annotations

import asyncio
import json
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
     'kind': 'documentation', 'rationale': f'Verified evidence {index}'}
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
    curriculum = [{'week': 1, 'title': 'Function foundations',
                   'outcomes': ['Define and call a function', 'Validate a result'],
                   'source_urls': [sources[0]['url']], 'overview': 'Learn by building.',
                   'estimated_hours': 3, 'lessons': []}]
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
            assert course["assessment"]["quiz_items"]
            assert course["assessment"]["assignment"]["deliverables"]
        finally:
            reset = client.put(
                "/analytics/settings/agent-provider", headers=admin, json={"provider": "mock"}
            )
            assert reset.status_code == 200, reset.text
