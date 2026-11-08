"""The real Deep Agents graph, driven by a scripted model: researching through a fake browser,
and building courses through the real course MCP server."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
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
        if isinstance(step, Exception):
            raise step
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


def test_researcher_saves_pages_with_soft_feedback_and_publishes_them_live(tmp_path, monkeypatch):
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
        activity = client.get(f"/research-runs/{run['id']}/activity", headers=learner).json()
        other = client.post("/auth/register", json={"email": f"o-{uuid4().hex}@example.com", "password": "LearnerPass123!"})
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/research-runs/{run['id']}", headers=other_headers).status_code == 404
        assert client.get(f"/research-runs/{run['id']}/activity", headers=other_headers).status_code == 404

    assert not script, "the agent stopped before finishing the script"
    assert offered[0] == ["browser_read", "browser_search", "compact_conversation", "read_file", "save_page", "set_coverage"]
    assert "name: plan" in replies[1]
    assert "Saved" in replies[5] and "has not been read" in replies[5]
    assert live_snapshots == [2]
    assert run["status"] == "completed" and run["error"] is None
    assert run["coverage"] == [{"id": "basics", "question": "How is a Python function defined?", "status": "covered"}]
    assert [page["url"] for page in run["pages"]] == ["https://docs.example.com/never-read", READ_URL]
    session = next(item for item in trace["sessions"] if item["agent_name"] == "Researcher")
    assert {tool["tool_name"] for tool in session["tool_invocations"]} >= {"browser_search", "browser_read", "save_page"}
    browser_events = activity["sessions"][0]["activity"]
    assert any(event["tool"] == "browser_search" and event["input"]["query"] for event in browser_events)
    assert any(event["tool"] == "browser_read" and event["output"]["pages"][0]["content"] for event in browser_events)


def test_browser_mcp_server_exposes_only_search_and_read(tmp_path, monkeypatch):
    fake_browser = tmp_path / "fake_agent_browser.py"
    _write_fake_browser(fake_browser)
    monkeypatch.setenv("AGENT_BROWSER_COMMAND", f"{sys.executable} {fake_browser}")

    async def tool_names():
        async with browser_tools() as tools:
            search = next(tool for tool in tools if tool.name == "browser_search")
            assert search.args_schema["properties"]["query"]["type"] == "string"
            assert search.metadata["annotations"]["readOnlyHint"] is True
            assert json.loads(await search.ainvoke({"query": ""}))["error"]["code"] == "invalid_query"
            assert "Error" in await search.ainvoke({})
            return sorted(tool.name for tool in tools)

    assert asyncio.run(tool_names()) == ["browser_read", "browser_search"]


SOURCE_URL = "https://docs.example.com/functions"
SOURCE_TEXT = "Defining functions\n\nA def statement binds a name to a function object.\nThe body is indented.\n"
COVERAGE = [
    {"id": "basics", "question": "How is a Python function defined?", "status": "covered"},
    {"id": "lambdas", "question": "What is a lambda expression?", "status": "missing"},
]


@pytest.mark.parametrize("initial_sources_available", [True, False])
def test_course_builder_coordinates_research_and_writer_through_real_mcp(monkeypatch, initial_sources_available):
    class FakeLiteLLMGateway:
        async def create_trace_key(self, **_kwargs):
            return "test-session-trace-key"

        async def spend_logs(self, _api_key):
            return []

    fetched = []
    activity = []
    first_url = "https://docs.example.com/lambdas"
    second_url = "https://docs.example.com/returns"
    first_source = "s2" if initial_sources_available else "s1"
    second_source = "s3" if initial_sources_available else "s2"

    async def read_pages(urls):
        fetched.append(urls)
        if not initial_sources_available:
            raise RuntimeError("Initial source unavailable")
        return {SOURCE_URL: SOURCE_TEXT}

    async def browser_search(query: str) -> dict:
        """Search sources for the assignment."""
        return {"results": [{"url": first_url, "title": "Lambdas"}]}

    async def browser_read(urls: list[str]) -> dict:
        """Read pages for the assignment."""
        return {
            "pages": [
                {
                    "url": url,
                    "title": "Focused source",
                    "status": "ok",
                    "content": "Lambda expressions create functions.\nReturn passes a value to the caller.",
                }
                for url in urls
            ]
        }

    @asynccontextmanager
    async def delegated_browser():
        yield [
            StructuredTool.from_function(coroutine=browser_search),
            StructuredTool.from_function(coroutine=browser_read),
        ]

    def record_activity():
        activity.extend(c.activity for c in course_service.live.values())
        return AIMessage(content="Saved source s2; lambda functions need a return example.")

    outline = [
        {
            "id": "c1",
            "title": "Functions",
            "sections": [
                {"id": "c1-s1", "title": "Definitions", "covers": ["basics"]},
                {"id": "c1-s2", "title": "Lambdas", "covers": ["lambdas"]},
            ],
        }
    ]
    script[:] = [
        _call("read_file", {"file_path": "/skills/outline/SKILL.md", "limit": 1000}),
        _call("list_sources", {}),
        _call("set_outline", {"chapters": outline}),
        _call(
            "task",
            {"subagent_type": "researcher", "description": "Find lambda sources for a beginner. Existing source: s1."},
        ),
        _call("read_file", {"file_path": "/skills/researcher/plan/SKILL.md", "limit": 1000}),
        _call("browser_search", {"query": "lambda functions"}),
        _call("browser_read", {"urls": [first_url]}),
        # Short metadata, an arbitrary kind and unknown coverage IDs are accepted.
        _call("save_page", {"url": first_url, "title": "L", "why": "x", "kind": "guide", "covers": ["new-topic"]}),
        record_activity,
        _call(
            "task",
            {"subagent_type": "writer", "description": "Write c1-s1 from s1 and s2. Report missing information."},
        ),
        _call("read_file", {"file_path": "/skills/writer/write/SKILL.md", "limit": 1000}),
        _call("read_source", {"source_id": first_source}),
        _call(
            "write_section",
            {"section_id": "c1-s1", "sentences": [{"text": "A function has a body.", "kind": "lesson"}]},
        ),
        AIMessage(content="Wrote c1-s1. Please find an example explaining return values."),
        _call(
            "task",
            {
                "subagent_type": "researcher",
                "description": "Find a return-value example to improve c1-s1. Sources s1 and s2 already exist.",
            },
        ),
        _call("browser_read", {"urls": [second_url]}),
        _call("save_page", {"url": second_url}),
        AIMessage(content="Saved s3 explaining return values."),
        _call("task", {"subagent_type": "writer", "description": "Revise c1-s1 with s3 and write c1-s2 using s2."}),
        _call("read_section", {"section_id": "c1-s1"}),
        _call("read_source", {"source_id": second_source}),
        _call(
            "write_section",
            {
                "section_id": "c1-s1",
                "sentences": [
                    {
                        "text": "Return passes a value to the caller.",
                        "cites": [{"passage": f"{second_source}.p2", "quote": "paraphrased excerpt"}],
                    },
                    {"text": "Here are 2 examples.", "paragraph": 2},
                ],
            },
        ),
        _call(
            "write_section",
            {
                "section_id": "c1-s2",
                "sentences": [
                    {"text": "Lambda expressions create functions.", "cites": [{"passage": f"{first_source}.p1"}]},
                ],
            },
        ),
        AIMessage(content="Wrote c1-s1 and c1-s2."),
        _call("check_course", {}),
        AIMessage(content="Course assembled."),
        # An empty model result remains a successful run, without a content rejection.
        AIMessage(content="Nothing more to write."),
        # A real execution failure preserves already-saved sections.
        _call("set_outline", {"chapters": outline}),
        _call("task", {"subagent_type": "writer", "description": "Write c1-s1."}),
        _call("write_section", {"section_id": "c1-s1", "sentences": [{"text": "Saved before failure."}]}),
        RuntimeError("Writer model unavailable"),
    ]
    offered.clear(), replies.clear()
    monkeypatch.setattr("app.harness.runtime.LiteLLMGateway", FakeLiteLLMGateway)
    monkeypatch.setattr(
        "app.harness.deep_agents.DeepAgentRuntime._model",
        lambda self, api_key, metadata: ScriptedModel(
            model="litellm_proxy/agent-model", api_base="http://litellm", api_key=api_key
        ),
    )
    monkeypatch.setattr(course_service, "read_pages", read_pages)
    monkeypatch.setattr(course_service, "browser_tools", delegated_browser)
    email = f"c-{uuid4().hex}@example.com"

    async def research_run(status="completed"):
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == email))
            request = LearningRequest(
                user_id=user.id, topic="Python functions", level="beginner", hours_per_week=3, weeks=1
            )
            db.add(request)
            await db.flush()
            run = AgentRun(
                learning_request_id=request.id,
                harness="deep-agents",
                status=status,
                result={"coverage": COVERAGE, "pages": [{**_page(SOURCE_URL), "title": "Functions"}], "error": None},
            )
            db.add(run)
            await db.commit()
            return run.id

    with TestClient(app) as client:
        registration = client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
        learner = {"Authorization": f"Bearer {registration.json()['access_token']}"}
        client.get("/research-runs", headers=learner)
        research_id = client.portal.call(research_run)
        running_id = client.portal.call(research_run, "running")
        assert client.post(f"/research-runs/{running_id}/courses", headers=learner).status_code == 409
        first = client.post(f"/research-runs/{research_id}/courses", headers=learner)
        assert first.status_code == 202, first.text
        course = client.get(f"/courses/{first.json()['id']}", headers=learner).json()
        second = client.post(f"/research-runs/{research_id}/courses", headers=learner).json()
        empty = client.get(f"/courses/{second['id']}", headers=learner).json()
        third = client.post(f"/research-runs/{research_id}/courses", headers=learner).json()
        failed = client.get(f"/courses/{third['id']}", headers=learner).json()
        unchanged = client.get(f"/courses/{course['id']}", headers=learner).json()
        versions = client.get(f"/research-runs/{research_id}/courses", headers=learner).json()
        other = client.post(
            "/auth/register", json={"email": f"o-{uuid4().hex}@example.com", "password": "LearnerPass123!"}
        )
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/courses/{course['id']}", headers=other_headers).status_code == 404

    assert not script, "the agents stopped before finishing the script"
    builder_tools = offered[0]
    assert "task" in builder_tools and "write_section" not in builder_tools
    assert "browser_read" not in builder_tools
    researcher_tools = next(names for names in offered if "browser_read" in names)
    writer_tools = next(names for names in offered if "write_section" in names)
    assert "set_outline" not in researcher_tools and "write_section" not in researcher_tools
    assert "task" not in researcher_tools and "task" not in writer_tools
    assert "set_outline" not in writer_tools and "browser_read" not in writer_tools
    assert any("name: plan" in reply for reply in replies)
    assert any("name: write" in reply for reply in replies)
    assert any(f'"source": "{first_source}"' in reply for reply in replies)
    assert any(f'"source": "{second_source}"' in reply for reply in replies)
    assert any("A function has a body." in reply for reply in replies)
    assert any(line and "researcher" in line for line in activity)
    initial_urls = [SOURCE_URL] if initial_sources_available else []
    assert fetched == [[SOURCE_URL]] * (1 if initial_sources_available else 3)
    assert course["status"] == "completed" and course["error"] is None and course["gaps"] == []
    assert course["chapters"] == outline
    assert [s["url"] for s in course["sources"]] == [*initial_urls, first_url, second_url]
    assert all(s["warning"] is None for p in course["sections"]["c1-s1"] for s in p)
    assert len(course["sections"]["c1-s1"]) == 2
    assert "c1-s2" in course["sections"]
    assert empty["status"] == "completed" and empty["sections"] == {}
    assert [s["url"] for s in empty["sources"]] == initial_urls
    assert failed["status"] == "failed" and "Writer model unavailable" in failed["error"]
    assert failed["sections"]["c1-s1"][0][0]["text"] == "Saved before failure."
    assert unchanged["sections"] == course["sections"] and unchanged["sources"] == course["sources"]
    assert [(v["version"], v["status"]) for v in versions] == [(3, "failed"), (2, "completed"), (1, "completed")]
