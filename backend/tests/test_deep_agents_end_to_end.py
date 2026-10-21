"""Deterministic end-to-end proof of the browser/Deep Agents learning workflow."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from browser_mcp.client import AgentBrowserClient
from browser_mcp.gateway import BrowserGateway
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


def test_fake_browser_and_deep_agent_research_a_topic(tmp_path, monkeypatch):
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
            run = client.get(f"/learning-runs/{started['id']}", headers=learner).json()
            assert set(run) == {"id", "harness", "research", "sessions"}
            assert len(run["research"]["sources"]) == 5
            assert len(run["research"]["visited_sources"]) == 5
            assert run["research"]["stop_reason"] == "coverage_satisfied"
            assert all(item["status"] == "covered" for item in run["research"]["coverage"])
            verified_urls = {source["url"] for source in run["research"]["sources"]}
            assert set(run["sessions"]) == {"Researcher"}

            trace = client.get(f"/learning-runs/{run['id']}/trace", headers=learner)
            assert trace.status_code == 200, trace.text
            trace_body = trace.json()
            session_names = {session["agent_name"] for session in trace_body["sessions"]}
            assert {
                "BrowserResearch", "ResearchQueryPlanner", "ResearchSelector",
                "ResearchSynthesisPart1", "ResearchCoverageRound1",
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

            other_email = f"other-{uuid4().hex}@example.com"
            other_registration = client.post(
                "/auth/register",
                json={"email": other_email, "password": "LearnerPass123!"},
            )
            other = {
                "Authorization": f"Bearer {other_registration.json()['access_token']}"
            }
            assert client.get(f"/learning-runs/{run['id']}/trace", headers=other).status_code == 404
            assert client.get(f"/learning-runs/{run['id']}", headers=other).status_code == 404
        finally:
            assert admin
