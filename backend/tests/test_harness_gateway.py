import json
from datetime import datetime

import httpx
import pytest

from app.core.config import get_settings
from app.harness.gateway import LiteLLMGateway
from app.harness.spend_logs import model_event


@pytest.mark.asyncio
async def test_trace_key_is_scoped_to_the_session(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-master")
    monkeypatch.setenv("LITELLM_MODEL", "agent-model")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-master"
        assert request.url.path == "/key/generate"
        body = json.loads(request.content)
        assert body["models"] == ["agent-model"]
        assert body["metadata"]["session_id"] == "session-1"
        assert body["metadata"]["harness"] == "deep-agents"
        return httpx.Response(200, json={"key": "sk-session-trace"})

    gateway = LiteLLMGateway(transport=httpx.MockTransport(handler))
    key = await gateway.create_trace_key(run_id="run-1", session_id="session-1", harness="deep-agents")
    assert key == "sk-session-trace"
    get_settings.cache_clear()


def _log(**overrides):
    return {
        "request_id": "call-1",
        "call_type": "responses",
        "model": "openai/z-ai/glm-5.3-flash",
        "model_group": "agent-model",
        "metadata": {"spend_logs_metadata": {"run_id": "run-1", "session_id": "session-1", "agent_role": "Planner"}},
        "messages": [{"role": "user", "content": "inspect this"}],
        "response": {"output_text": "done"},
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "spend": 0.00042,
        "request_duration_ms": None,
        "status": "success",
        "startTime": datetime(2026, 8, 8, 10, 0, 0),
        "endTime": datetime(2026, 8, 8, 10, 0, 1),
    } | overrides


def test_litellm_spend_log_row_becomes_a_model_timeline_event():
    event = model_event(_log())
    assert (event["run_id"], event["session_id"]) == ("run-1", "session-1")
    assert event["event_type"] == "model"
    assert event["name"] == "litellm.responses"
    assert event["status"] == "completed"
    assert event["input_payload"]["messages"][0]["content"] == "inspect this"
    assert event["output_payload"] == {"output_text": "done"}
    assert (event["prompt_tokens"], event["completion_tokens"], event["total_cost_usd"]) == (12, 4, 0.00042)
    assert event["duration_ms"] == 1000


def test_research_model_inputs_stay_redacted():
    log = _log(status="failure")
    log["metadata"]["spend_logs_metadata"]["agent_role"] = "ResearchSynthesisPart1"
    event = model_event(log)
    assert event["input_payload"] == {"redacted": True, "reason": "ephemeral research evidence"}
    assert event["status"] == "failed"
