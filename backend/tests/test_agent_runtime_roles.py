from types import SimpleNamespace

import pytest

import app.harness.runtime as runtime_module
from app.harness.providers.cli import ProviderExecution, ToolInvocationEvent
from app.harness.providers.factory import get_runtime
from app.harness.runtime import AgentHarness


def test_researcher_gemini_enables_only_learning_browser(monkeypatch):
    monkeypatch.delenv("GEMINI_CLI_COMMAND", raising=False)

    runtime = get_runtime("gemini-cli", "Researcher")

    assert runtime.stream_json is True
    assert "stream-json" in runtime.command
    assert runtime.command[-1] == "learning-browser"
    assert runtime.timeout_seconds == 300


def test_gemini_prefers_pinned_project_local_entrypoint(monkeypatch):
    monkeypatch.delenv("GEMINI_CLI_COMMAND", raising=False)

    runtime = get_runtime("gemini-cli", "Researcher")

    assert runtime.command[0].casefold().endswith("node.exe") or runtime.command[0].casefold().endswith("/node")
    assert runtime.command[1].replace("\\", "/").endswith(
        "node_modules/@google/gemini-cli/bundle/gemini.js"
    )


def test_non_researcher_gemini_disables_browser_and_uses_json(monkeypatch):
    monkeypatch.delenv("GEMINI_CLI_COMMAND", raising=False)

    for role in ("Planner", "Examiner", None):
        runtime = get_runtime("gemini-cli", role)
        assert runtime.stream_json is False
        assert "stream-json" not in runtime.command
        assert "json" in runtime.command
        assert runtime.command[-1] == "browser-disabled"


def test_other_provider_commands_are_unchanged(monkeypatch):
    monkeypatch.delenv("CODEX_COMMAND", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CLI_COMMAND", raising=False)

    assert get_runtime("codex", "Researcher").command == ["codex", "exec", "--json", "-"]
    assert get_runtime("antigravity-cli", "Researcher").command == ["agy", "--output-format", "json"]


def test_gemini_command_override_cannot_omit_role_safety_flags(monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_COMMAND", "custom-gemini --model fast")

    runtime = get_runtime("gemini-cli", "Researcher")

    assert runtime.command[:3] == ["custom-gemini", "--model", "fast"]
    assert runtime.command[-6:] == [
        "--output-format", "stream-json", "--approval-mode", "plan",
        "--allowed-mcp-server-names", "learning-browser",
    ]


@pytest.mark.asyncio
async def test_harness_persists_sanitized_tools_but_not_internal_evidence(monkeypatch):
    tool_event = ToolInvocationEvent(
        "browser_read", "success",
        {"urls": ["https://example.com/paper"], "domains": ["example.com"], "result_count": 1},
        duration_ms=25,
    )
    execution = ProviderExecution(
        {"topic": "Attention", "sources": []},
        (tool_event,),
        frozenset({"https://example.com/paper"}),
    )

    class Runtime:
        async def execute(self, _prompt):
            return execution

    class Db:
        async def flush(self):
            pass

    session = SimpleNamespace(
        id="session-id", agent_name="Researcher", status="active",
        output_payload=None, error_message=None, completed_at=None, duration_ms=None,
    )
    audit_calls = []

    async def get(_session_id):
        return session

    async def append(*_args):
        pass

    async def audit(*args, **kwargs):
        audit_calls.append((args, kwargs))

    monkeypatch.setattr(runtime_module, "get_runtime", lambda *_args: Runtime())
    monkeypatch.setattr(runtime_module, "record_tool_invocation", audit)
    harness = AgentHarness("gemini-cli", Db())
    monkeypatch.setattr(harness, "get", get)
    monkeypatch.setattr(harness, "_append", append)

    result = await harness.resume_and_run("session-id", "research")

    assert result == {"topic": "Attention", "sources": []}
    assert result.visited_urls == frozenset({"https://example.com/paper"})
    assert session.output_payload == {"topic": "Attention", "sources": []}
    assert "visited_urls" not in session.output_payload
    assert audit_calls[0][0][2:5] == ("browser_read", "success", tool_event.metadata)
    assert audit_calls[0][1]["duration_ms"] == 25
