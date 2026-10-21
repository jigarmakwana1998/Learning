"""The real Deep Agents graph, driven by a scripted model, researching through a fake browser."""

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

from app.agents.researcher import browser_tools
from app.main import app
from app.services.research_service import research_service
from browser_mcp.client import AgentBrowserClient
from browser_mcp.gateway import BrowserGateway

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
        replies.append(messages[-1].content)
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
