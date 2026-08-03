import asyncio
import json

import pytest

from app.harness.providers.cli import CliRuntime


class FakeProcess:
    returncode = 0

    async def communicate(self, _input):
        return json.dumps({"response": '{"topic":"Attention","sources":[]}', "stats": {}}).encode(), b""


@pytest.mark.asyncio
async def test_gemini_runtime_maps_local_env_and_unwraps_response(monkeypatch):
    captured = {}

    async def create_process(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    # Windows environment keys are case-insensitive, so delete canonical names first.
    monkeypatch.setenv("gemini_api_key", "test-key-not-a-real-secret")
    monkeypatch.setenv("project_id", "projects/784566960532")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    result = await CliRuntime("gemini-cli", ["gemini", "--output-format", "json"], "GEMINI_CLI_COMMAND", prompt_flag="-p").execute("teach attention")

    assert result == {"topic": "Attention", "sources": []}
    assert captured["command"][-2:] == ("-p", "teach attention")
    assert captured["kwargs"]["stdin"] is None
    assert captured["kwargs"]["env"]["GEMINI_API_KEY"] == "test-key-not-a-real-secret"
    assert captured["kwargs"]["env"]["GOOGLE_CLOUD_PROJECT"] == "projects/784566960532"
    assert captured["kwargs"]["env"]["GEMINI_CLI_TRUST_WORKSPACE"] == "true"


def test_gemini_response_can_be_json_fenced():
    assert CliRuntime._parse_response('{"response":"```json\\n{\\"curriculum\\": []}\\n```"}') == {"curriculum": []}
