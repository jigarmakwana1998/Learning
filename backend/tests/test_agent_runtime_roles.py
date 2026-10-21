import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.harness.deep_agents as deep_agents_module
import app.harness.runtime as runtime_module
from app.agents.contracts import output_schema_for
from app.core.config import Settings
from app.harness.deep_agents import (
    AgentEventCollector,
    DeepAgentExecution,
    DeepAgentRuntime,
    ToolInvocationEvent,
)
from app.harness.runtime import AgentHarness


def test_deep_agent_routes_model_through_litellm_and_maps_medium_reasoning():
    settings = Settings(
        agent_reasoning_effort="medium",
        litellm_base_url="http://litellm:4000",
        litellm_model="agent-model",
    )

    model = DeepAgentRuntime(settings)._model("session-key", {"session_id": "session-1"})

    assert model.model == "litellm_proxy/agent-model"
    assert model.api_base == "http://litellm:4000"
    assert model.api_key == "session-key"
    assert model.model_kwargs["reasoning_effort"] == "high"
    assert model.model_kwargs["extra_body"]["chat_template_kwargs"]["clear_thinking"] is True
    assert json.loads(model.extra_headers["x-litellm-spend-logs-metadata"]) == {
        "session_id": "session-1"
    }


def test_every_workflow_role_has_a_structured_output_contract():
    assert output_schema_for("ResearchQueryPlanner") is not None
    assert output_schema_for("ResearchSelector") is not None
    assert output_schema_for("ResearchSynthesisPart3") is not None
    assert output_schema_for("ResearchCoverageRound3") is not None


@pytest.mark.asyncio
async def test_mcp_tools_are_scoped_to_configured_roles(monkeypatch):
    captured = []

    class Client:
        def __init__(self, connections, **kwargs):
            captured.append((connections, kwargs))

        async def get_tools(self):
            return ["browser-tool"]

    monkeypatch.setattr(deep_agents_module, "MultiServerMCPClient", Client)
    settings = Settings(
        agent_mcp_enabled=True,
        agent_mcp_roles={"Researcher"},
        mcp_servers={"browser": {"transport": "http", "url": "http://mcp.test"}},
    )
    runtime = DeepAgentRuntime(settings)

    assert await runtime._mcp_tools("Planner") == []
    assert await runtime._mcp_tools("Researcher") == ["browser-tool"]
    assert captured == [
        (
            {"browser": {"transport": "http", "url": "http://mcp.test"}},
            {"tool_name_prefix": True},
        )
    ]


@pytest.mark.asyncio
async def test_tool_collector_redacts_browser_content_and_keeps_visit_evidence():
    collector = AgentEventCollector()
    run_id = uuid4()
    await collector.on_tool_start(
        {"name": "browser_read"},
        "ignored",
        run_id=run_id,
        inputs={"urls": ["https://example.com/paper"]},
    )
    await collector.on_tool_end(
        {
            "content": json.dumps(
                {
                    "pages": [
                        {
                            "url": "https://example.com/paper",
                            "title": "Paper",
                            "status": "ok",
                            "content": "UNTRUSTED_PAGE_BODY",
                        }
                    ]
                }
            )
        },
        run_id=run_id,
    )

    event = collector.tool_events[0]
    assert event.metadata["results"] == [
        {"url": "https://example.com/paper", "title": "Paper", "status": "ok"}
    ]
    assert "UNTRUSTED_PAGE_BODY" not in json.dumps(event.metadata)
    assert collector.visited_urls == {"https://example.com/paper"}


@pytest.mark.asyncio
async def test_harness_persists_sanitized_tools_but_not_internal_evidence(monkeypatch):
    tool_event = ToolInvocationEvent(
        "browser_read",
        "success",
        {"urls": ["https://example.com/paper"], "domains": ["example.com"], "result_count": 1},
        duration_ms=25,
    )
    execution = DeepAgentExecution(
        {"topic": "Attention", "sources": []},
        (tool_event,),
        frozenset({"https://example.com/paper"}),
    )

    class Runtime:
        async def execute(self, prompt, **_kwargs):
            assert prompt == "UNTRUSTED_PAGE_BODY"
            return execution

    class Gateway:
        async def create_trace_key(self, **_kwargs):
            return "test-trace-key"

        async def spend_logs(self, _api_key):
            return [{"messages": [{"role": "user", "content": "UNTRUSTED_PAGE_BODY"}]}]

    class Db:
        async def flush(self):
            pass

    session = SimpleNamespace(
        id="session-id",
        agent_run_id="run-id",
        agent_name="Researcher",
        status="active",
        output_payload=None,
        error_message=None,
        completed_at=None,
        duration_ms=None,
    )
    audit_calls = []
    appended = []
    trace_calls = []

    async def get(_session_id):
        return session

    async def append(*args):
        appended.append(args)

    async def audit(*args, **kwargs):
        audit_calls.append((args, kwargs))

    async def trace(*args, **kwargs):
        trace_calls.append((args, kwargs))

    monkeypatch.setattr(runtime_module, "DeepAgentRuntime", lambda: Runtime())
    monkeypatch.setattr(runtime_module, "LiteLLMGateway", Gateway)
    monkeypatch.setattr(runtime_module, "record_tool_invocation", audit)
    monkeypatch.setattr(runtime_module, "record_trace_event", trace)
    harness = AgentHarness("deep-agents", Db())
    monkeypatch.setattr(harness, "get", get)
    monkeypatch.setattr(harness, "_append", append)

    result = await harness.resume_and_run(
        "session-id",
        "UNTRUSTED_PAGE_BODY",
        persisted_prompt="Ephemeral research evidence omitted.",
    )

    assert result == {"topic": "Attention", "sources": []}
    assert result.visited_urls == frozenset({"https://example.com/paper"})
    assert session.output_payload == {"topic": "Attention", "sources": []}
    assert "visited_urls" not in session.output_payload
    assert audit_calls[0][0][2:5] == ("browser_read", "success", tool_event.metadata)
    assert audit_calls[0][1]["duration_ms"] == 25
    assert appended[0][2] == "Ephemeral research evidence omitted."
    assert "UNTRUSTED_PAGE_BODY" not in json.dumps(trace_calls, default=str)
    assert any(
        call[1].get("input_payload") == {
            "redacted": True,
            "reason": "ephemeral research evidence",
        }
        for call in trace_calls
    )
