import json

import httpx
import pytest

import app.harness.runtime as harness_runtime_module
from app.core.config import get_settings
from app.harness.gateway import LiteLLMGateway
from app.harness.providers.factory import get_runtime
from app.harness.runtime import AgentHarness


@pytest.mark.parametrize("harness", ["codex", "gemini-cli", "antigravity-cli"])
def test_live_harnesses_receive_the_litellm_gateway_environment(harness, monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "test-gateway-key")
    monkeypatch.setenv("LITELLM_MODEL", "agent-model")
    get_settings.cache_clear()
    runtime = get_runtime(harness)
    environment = runtime._gateway_environment()
    assert environment["OPENAI_BASE_URL"] == "http://litellm:4000/v1"
    assert environment["GOOGLE_GEMINI_BASE_URL"] == "http://litellm:4000"
    assert environment["OPENAI_API_KEY"] == "test-gateway-key"
    assert environment["GEMINI_API_KEY"] == "test-gateway-key"
    scoped_environment = runtime._gateway_environment("session-trace-key")
    assert scoped_environment["OPENAI_API_KEY"] == "session-trace-key"
    assert scoped_environment["GEMINI_API_KEY"] == "session-trace-key"
    assert "agent-model" in runtime.command
    if harness == "gemini-cli":
        assert runtime.prompt_flag == "-p"
    if harness == "antigravity-cli":
        assert "--print" in runtime.command
    get_settings.cache_clear()


def test_litellm_is_not_an_agent_harness():
    with pytest.raises(KeyError):
        get_runtime("litellm")


def test_cli_event_stream_extracts_tool_events_and_final_result(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-gateway-key")
    get_settings.cache_clear()
    runtime = get_runtime("codex")
    events = runtime._parse_events('\n'.join([
        '{"type":"item.completed","item":{"type":"command_execution","command":"rg TODO","output":"done"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"topic\\":\\"Tracing\\",\\"sources\\":[]}"}}',
    ]))
    assert events[0]["item"]["type"] == "command_execution"
    assert runtime._extract_result(events) == {"topic": "Tracing", "sources": []}
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_trace_key_correlates_session_with_individual_spend_logs(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-master")
    monkeypatch.setenv("LITELLM_MODEL", "agent-model")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-master"
        if request.url.path == "/key/generate":
            body = json.loads(request.content)
            assert body["models"] == ["agent-model"]
            assert body["metadata"]["session_id"] == "session-1"
            return httpx.Response(200, json={"key": "sk-session-trace"})
        assert request.url.path == "/spend/logs"
        assert request.url.params["api_key"] == "sk-session-trace"
        assert request.url.params["summarize"] == "false"
        return httpx.Response(200, json=[{"request_id": "call-1", "spend": 0.001}])

    gateway = LiteLLMGateway(transport=httpx.MockTransport(handler))
    key = await gateway.create_trace_key(run_id="run-1", session_id="session-1", harness="codex")
    assert key == "sk-session-trace"
    assert await gateway.spend_logs(key) == [{"request_id": "call-1", "spend": 0.001}]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_litellm_spend_log_becomes_a_model_timeline_event(monkeypatch):
    captured = []

    async def capture_event(db, **event):
        captured.append(event)

    monkeypatch.setattr(harness_runtime_module, "record_trace_event", capture_event)
    harness = AgentHarness.__new__(AgentHarness)
    harness.db = object()
    session = type("Session", (), {"id": "session-1", "agent_run_id": "run-1"})()
    await harness._record_model_events(session, [{
        "request_id": "call-1",
        "call_type": "responses",
        "model": "openai/gpt-5-mini",
        "model_group": "agent-model",
        "messages": [{"role": "user", "content": "inspect this"}],
        "response": {"output_text": "done"},
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "spend": 0.00042,
        "request_duration_ms": 87,
        "startTime": "2026-08-08T10:00:00Z",
    }])

    assert captured[0]["event_type"] == "model"
    assert captured[0]["name"] == "litellm.responses"
    assert captured[0]["input_payload"]["messages"][0]["content"] == "inspect this"
    assert captured[0]["output_payload"] == {"output_text": "done"}
    assert captured[0]["prompt_tokens"] == 12
    assert captured[0]["completion_tokens"] == 4
    assert captured[0]["total_cost_usd"] == 0.00042
