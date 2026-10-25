"""The real Deep Agents graph, driven by a scripted model: researching through a fake browser,
and building courses through the real course MCP server."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langchain_litellm import ChatLiteLLM

from sqlalchemy import select

from app.agents.researcher import browser_tools
from app.main import app
from app.services.course_service import course_service
from app.services.research_service import research_service
from browser_mcp.client import AgentBrowserClient
from browser_mcp.gateway import BrowserGateway
from learning_db.models import AgentRun, LearningRequest, User
from learning_db.session import SessionLocal

READ_URL = "https://docs.example.com/source-0"


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
        result = {'title': 'Defining functions'}
    elif item[:3] == ['get', 'text', 'body']:
        result = {'content': 'A def statement binds a name to a function object.'}
    elif item[0] == 'close':
        result = {'closed': True}
    else:
        result = {}
    results.append({'success': True, 'result': result})
print(json.dumps(results))
""",
        encoding="utf-8",
    )


def _call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": uuid4().hex}])


def _page(url: str) -> dict:
    return {
        "url": url,
        "title": "Defining functions",
        "kind": "documentation",
        "why": "Shows how def statements define and name functions.",
        "key_points": ["A def statement binds a name to a function object."],
        "covers": ["basics"],
    }


class ScriptedModel(ChatLiteLLM):
    """A LiteLLM model (so the litellm harness profile applies) that replays a fixed conversation."""

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        offered.append(sorted(tool["function"]["name"] for tool in kwargs.get("tools", [])))
        replies.append(str(messages[-1].content))
        step = script.pop(0)
        return ChatResult(generations=[ChatGeneration(message=step() if callable(step) else step)])


offered: list[list[str]] = []
replies: list[str] = []
script: list = []
live_snapshots: list[int] = []


def _snapshot_then(message: AIMessage):
    def step():
        live_snapshots.extend(len(progress.pages) for progress in research_service.live.values())
        return message
    return step


def test_researcher_saves_only_read_pages_and_publishes_them_live(tmp_path, monkeypatch):
    class FakeLiteLLMGateway:
        async def create_trace_key(self, **_kwargs):
            return "test-session-trace-key"

        async def spend_logs(self, _api_key):
            return []

    fake_browser = tmp_path / "fake_agent_browser.py"
    _write_fake_browser(fake_browser)
    gateway = BrowserGateway(
        client=AgentBrowserClient(command=[sys.executable, str(fake_browser)]),
        resolver=_public_resolver,
    )

    async def browser_search(query: str) -> dict:
        """Search public web pages."""
        return {"status": "ok", "query": query, "results": [{"title": "Defining functions", "url": READ_URL}]}

    async def browser_read(urls: list[str]) -> dict:
        """Read up to four public HTTPS pages."""
        return await gateway.browser_read(urls)

    @asynccontextmanager
    async def fake_browser_tools():
        yield [StructuredTool.from_function(coroutine=browser_search), StructuredTool.from_function(coroutine=browser_read)]

    script[:] = [
        _call("read_file", {"file_path": "/skills/plan/SKILL.md", "limit": 1000}),
        _call("set_coverage", {"items": [{"id": "basics", "question": "How is a Python function defined?"}]}),
        _call("browser_search", {"query": "Python functions def statement official tutorial"}),
        _call("browser_read", {"urls": [READ_URL]}),
        _call("save_page", _page("https://docs.example.com/never-read")),
        _call("save_page", _page(READ_URL)),
        _snapshot_then(_call("set_coverage", {"items": [{"id": "basics", "question": "How is a Python function defined?", "status": "covered"}]})),
        AIMessage(content="Saved one page covering how functions are defined."),
    ]
    offered.clear(), replies.clear(), live_snapshots.clear()
    monkeypatch.setattr("app.harness.runtime.LiteLLMGateway", FakeLiteLLMGateway)
    monkeypatch.setattr(
        "app.harness.deep_agents.DeepAgentRuntime._model",
        lambda self, api_key, metadata: ScriptedModel(model="litellm_proxy/agent-model", api_base="http://litellm", api_key=api_key),
    )
    monkeypatch.setattr(research_service, "browser_tools", fake_browser_tools)

    with TestClient(app) as client:
        registration = client.post("/auth/register", json={"email": f"r-{uuid4().hex}@example.com", "password": "LearnerPass123!"})
        learner = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        started = client.post("/research-runs", headers=learner, json={"topic": "Python functions", "weeks": 1, "hours_per_week": 3})
        assert started.status_code == 202, started.text
        # TestClient runs background tasks before returning the response.
        run = client.get(f"/research-runs/{started.json()['id']}", headers=learner).json()
        trace = client.get(f"/research-runs/{run['id']}/trace", headers=learner).json()
        other = client.post("/auth/register", json={"email": f"o-{uuid4().hex}@example.com", "password": "LearnerPass123!"})
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/research-runs/{run['id']}", headers=other_headers).status_code == 404

    assert not script, "the agent stopped before finishing the script"
    assert offered[0] == ["browser_read", "browser_search", "compact_conversation", "read_file", "save_page", "set_coverage"]
    assert "name: plan" in replies[1]
    assert "not read in this run" in replies[5]
    assert live_snapshots == [1]
    assert run["status"] == "completed" and run["error"] is None
    assert run["coverage"] == [{"id": "basics", "question": "How is a Python function defined?", "status": "covered"}]
    assert [page["url"] for page in run["pages"]] == [READ_URL]
    session = next(item for item in trace["sessions"] if item["agent_name"] == "Researcher")
    assert {tool["tool_name"] for tool in session["tool_invocations"]} >= {"browser_search", "browser_read", "save_page"}


def test_browser_mcp_server_exposes_only_search_and_read(tmp_path, monkeypatch):
    fake_browser = tmp_path / "fake_agent_browser.py"
    _write_fake_browser(fake_browser)
    monkeypatch.setenv("AGENT_BROWSER_COMMAND", f"{sys.executable} {fake_browser}")

    async def tool_names():
        async with browser_tools() as tools:
            return sorted(tool.name for tool in tools)

    assert asyncio.run(tool_names()) == ["browser_read", "browser_search"]


SOURCE_URL = "https://docs.example.com/functions"
SOURCE_TEXT = "Defining functions\n\nA def statement binds a name to a function object.\nThe body is indented.\n"
COVERAGE = [
    {"id": "basics", "question": "How is a Python function defined?", "status": "covered"},
    {"id": "lambdas", "question": "What is a lambda expression?", "status": "missing"},
]


def _sentence(text: str, kind: str = "fact", quote: str | None = None) -> dict:
    return {"text": text, "kind": kind, "cites": [{"passage": "s1.p2", "quote": quote}] if quote else []}


def test_course_builder_writes_cited_versions_through_the_course_mcp_server(monkeypatch):
    class FakeLiteLLMGateway:
        async def create_trace_key(self, **_kwargs):
            return "test-session-trace-key"

        async def spend_logs(self, _api_key):
            return []

    fetched: list[list[str]] = []

    async def read_pages(urls):
        fetched.append(urls)
        return {SOURCE_URL: SOURCE_TEXT}

    outline = [{"id": "c1", "title": "Defining functions", "sections": [
        {"id": "c1-s1", "title": "The def statement", "covers": ["basics"]},
        {"id": "c1-s2", "title": "Calling functions", "covers": ["basics"]},
    ]}]
    script[:] = [
        _call("read_file", {"file_path": "/skills/outline/SKILL.md", "limit": 1000}),
        _call("list_sources", {}),
        _call("set_outline", {"chapters": outline}),
        _call("read_source", {"source_id": "s1"}),
        _call("write_section", {"section_id": "c1-s1", "paragraphs": [[_sentence("A def statement names a function.")]]}),
        _call("write_section", {"section_id": "c1-s1", "paragraphs": [[
            _sentence("A def statement binds a name to a function object.", quote="A def statement binds a name to a function object."),
            _sentence("Next, we look at the body.", "explanation"),
            _sentence("Python 3 kept the def statement.", quote="A def statement binds a name"),
        ]]}),
        _call("check_course", {}),
        AIMessage(content="Wrote one cited section."),
        # Version 2 writes nothing and fails, but version 1 is kept.
        AIMessage(content="Nothing to write."),
    ]
    offered.clear(), replies.clear()
    monkeypatch.setattr("app.harness.runtime.LiteLLMGateway", FakeLiteLLMGateway)
    monkeypatch.setattr(
        "app.harness.deep_agents.DeepAgentRuntime._model",
        lambda self, api_key, metadata: ScriptedModel(model="litellm_proxy/agent-model", api_base="http://litellm", api_key=api_key),
    )
    monkeypatch.setattr(course_service, "read_pages", read_pages)

    email = f"c-{uuid4().hex}@example.com"

    async def research_run(status: str = "completed") -> str:
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == email))
            request = LearningRequest(user_id=user.id, topic="Python functions", level="beginner", hours_per_week=3, weeks=1)
            db.add(request)
            await db.flush()
            pages = [{**_page(SOURCE_URL), "title": "Functions"}]
            run = AgentRun(learning_request_id=request.id, harness="deep-agents", status=status,
                           result={"coverage": COVERAGE, "pages": pages, "error": None})
            db.add(run)
            await db.commit()
            return run.id

    with TestClient(app) as client:
        registration = client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
        learner = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        client.get("/research-runs", headers=learner)  # creates the app user
        research_id = client.portal.call(research_run)
        running_id = client.portal.call(research_run, "running")
        assert client.post(f"/research-runs/{running_id}/courses", headers=learner).status_code == 409

        first = client.post(f"/research-runs/{research_id}/courses", headers=learner)
        assert first.status_code == 202, first.text
        # TestClient runs background tasks before returning the response.
        course = client.get(f"/courses/{first.json()['id']}", headers=learner).json()
        second = client.post(f"/research-runs/{research_id}/courses", headers=learner).json()
        versions = client.get(f"/research-runs/{research_id}/courses", headers=learner).json()
        failed = client.get(f"/courses/{second['id']}", headers=learner).json()
        listed = client.get("/research-runs", headers=learner).json()
        assert client.post(f"/research-runs/{course['id']}/courses", headers=learner).status_code == 404
        other = client.post("/auth/register", json={"email": f"o-{uuid4().hex}@example.com", "password": "LearnerPass123!"})
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/courses/{course['id']}", headers=other_headers).status_code == 404

    assert not script, "the agent stopped before finishing the script"
    assert offered[0] == [
        "check_course", "compact_conversation", "list_sources", "read_file",
        "read_source", "search_sources", "set_outline", "write_section",
    ]
    assert "name: outline" in replies[1]
    assert "Outline saved" in replies[3]
    assert '"s1.p2"' in replies[4]
    assert "Wrote c1-s1" in replies[5] and "Fact with no citation." in replies[5]
    assert "Not in the cited source: 3." in replies[6]
    assert '"c1-s2"' in replies[7] and '"lambdas"' in replies[7]
    assert fetched == [[SOURCE_URL]], "sources are fetched once per research run"

    assert course["status"] == "completed" and course["version"] == 1 and course["error"] is None
    assert course["gaps"] == ["Section not written: Calling functions", "What is a lambda expression?"]
    assert course["chapters"] == outline
    assert course["sources"] == [{"id": "s1", "url": SOURCE_URL, "title": "Functions"}]
    sentences = course["sections"]["c1-s1"][0]
    assert [(s["kind"], s["warning"]) for s in sentences] == [
        ("fact", None), ("explanation", None), ("fact", "Not in the cited source: 3."),
    ]
    assert failed["status"] == "failed" and failed["error"] == "The course builder wrote no sections."
    assert [(v["version"], v["status"]) for v in versions] == [(2, "failed"), (1, "completed")]
    assert {run["id"] for run in listed} == {research_id, running_id}
