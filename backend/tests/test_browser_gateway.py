import asyncio
import json

import pytest

from app.browser.client import AgentBrowserClient, AgentBrowserError
from app.browser.gateway import BrowserGateway
from app.browser.server import mcp
from app.mcp.tools import RESEARCH_TOOLS


def public_resolver(_host, port, *, type):
    return [(2, type, 6, "", ("93.184.216.34", port))]


class FakeBrowser:
    def __init__(self):
        self.calls = []
        self.closed = []

    async def run(self, session, host, *arguments):
        self.calls.append((session, host, arguments))
        if arguments[:2] == ("get", "url"):
            opened = next(call[2][1] for call in reversed(self.calls) if call[0] == session and call[2][0] == "open")
            return {"url": opened}
        if arguments[:2] == ("get", "title"):
            return {"title": "Example title"}
        if arguments[0] == "snapshot":
            return {
                "snapshot": '- link "Example" [ref=e1] [url="https://example.com/article"]\n'
                '- link "Private" [ref=e2] [url="https://localhost/secret"]'
            }
        if arguments[:3] == ("get", "text", "body"):
            return {"content": "A" * 6100}
        return {}

    async def close(self, session, host):
        self.closed.append((session, host))

    async def run_batch(self, session, host, commands):
        results = []
        for command in commands:
            if command[0] == "close":
                await self.close(session, host)
                results.append({"closed": True})
            else:
                results.append(await self.run(session, host, *command))
        return results


class FailedBrowser(FakeBrowser):
    async def run(self, session, host, *arguments):
        if arguments[0] == "open":
            from app.browser.client import AgentBrowserError

            raise AgentBrowserError("synthetic navigation failure")
        return await super().run(session, host, *arguments)


@pytest.mark.asyncio
async def test_search_uses_browser_page_validates_results_and_cleans_up():
    client = FakeBrowser()
    gateway = BrowserGateway(client=client, resolver=public_resolver)

    result = await gateway.browser_search("attention transformers", 5)

    assert result["status"] == "ok"
    assert result["engine"] == "duckduckgo"
    assert result["results"] == [{"title": "Example", "url": "https://example.com/article"}]
    assert client.calls[0][2][0] == "open"
    assert "duckduckgo.com" in client.calls[0][2][1]
    assert client.closed


@pytest.mark.asyncio
async def test_bing_rss_fallback_is_parsed_as_browser_content():
    class BingFallbackBrowser(FakeBrowser):
        async def run(self, session, host, *arguments):
            if arguments[0] == "snapshot":
                return {"snapshot": "No usable search results"}
            if arguments[:3] == ("get", "text", "body") and host == "www.bing.com":
                return {
                    "content": (
                        "<rss><channel><item><title>Attention Is All You Need</title>"
                        "<link>https://arxiv.org/abs/1706.03762</link></item></channel></rss>"
                    )
                }
            return await super().run(session, host, *arguments)

    gateway = BrowserGateway(client=BingFallbackBrowser(), resolver=public_resolver)

    result = await gateway.browser_search("attention transformers", 5)

    assert result["status"] == "ok"
    assert result["engine"] == "bing"
    assert result["results"] == [
        {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762"}
    ]


@pytest.mark.asyncio
async def test_read_revalidates_final_url_scrolls_bounds_content_and_cleans_up():
    client = FakeBrowser()
    gateway = BrowserGateway(client=client, resolver=public_resolver)

    result = await gateway.browser_read(["https://example.com/article"])

    page = result["pages"][0]
    assert page["status"] == "ok"
    assert page["content"] == "A" * 6000
    assert page["truncated"] is True
    assert page["content_is_untrusted"] is True
    assert sum(call[2][0] == "scroll" for call in client.calls) == 2
    assert client.closed


@pytest.mark.asyncio
async def test_read_rejects_private_url_without_launching_browser():
    client = FakeBrowser()
    gateway = BrowserGateway(client=client, resolver=public_resolver)
    result = await gateway.browser_read(["https://localhost/admin"])
    assert result["pages"][0]["error"]["code"] == "url_rejected"
    assert client.calls == []


@pytest.mark.asyncio
async def test_navigation_failure_still_closes_ephemeral_session():
    client = FailedBrowser()
    gateway = BrowserGateway(client=client, resolver=public_resolver)

    result = await gateway.browser_read(["https://example.com/article"])

    assert result["status"] == "unavailable"
    assert result["pages"][0]["error"]["code"] == "navigation_failed"
    assert client.closed


@pytest.mark.asyncio
async def test_tool_quotas_are_enforced():
    gateway = BrowserGateway(client=FakeBrowser(), resolver=public_resolver)
    for query in ("one", "two", "three", "four"):
        assert (await gateway.browser_search(query))["status"] == "ok"
    result = await gateway.browser_search("five")
    assert result["error"]["code"] == "quota_exceeded"

    second = BrowserGateway(client=FakeBrowser(), resolver=public_resolver)
    for index in range(3):
        assert (await second.browser_read([f"https://example.com/{index}-{offset}" for offset in range(4)]))["status"] == "ok"
    result = await second.browser_read(["https://example.com/too-many"])
    assert result["error"]["code"] == "quota_exceeded"


def test_only_two_research_tools_are_exposed():
    assert {tool.name for tool in RESEARCH_TOOLS} == {"browser_search", "browser_read"}


@pytest.mark.asyncio
async def test_stdio_mcp_server_exposes_only_safe_browser_tools():
    from app.browser.server import mcp

    assert {tool.name for tool in await mcp.list_tools()} == {"browser_search", "browser_read"}
    assert {tool.name for tool in mcp._tool_manager.list_tools()} == {"browser_search", "browser_read"}
    for tool in await mcp.list_tools():
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is True


def test_client_uses_argument_array_and_enforces_security_environment(monkeypatch):
    client = AgentBrowserClient(command=["agent-browser"])
    monkeypatch.setenv("AGENT_BROWSER_PROFILE", "unsafe-profile")
    monkeypatch.setenv("AGENT_BROWSER_ALLOWED_DOMAINS", "anything.example")
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-reach-browser")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-browser")
    environment = client._environment("example.com")
    assert "AGENT_BROWSER_PROFILE" not in environment
    assert "GEMINI_API_KEY" not in environment
    assert "DATABASE_URL" not in environment
    assert environment["AGENT_BROWSER_ALLOWED_DOMAINS"] == "example.com"
    assert environment["AGENT_BROWSER_CONTENT_BOUNDARIES"] == "1"
    assert environment["AGENT_BROWSER_IDLE_TIMEOUT_MS"] == "15000"
    assert environment["AGENT_BROWSER_NO_AUTO_DIALOG"] == "1"
    policy = json.loads(client.policy_path.read_text())
    assert policy == {
        "default": "deny",
        "allow": ["navigate", "snapshot", "scroll", "wait", "get", "url", "title", "text", "gettext", "close"],
    }


@pytest.mark.asyncio
async def test_client_passes_untrusted_url_as_one_subprocess_argument(monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b'{"success":true,"data":{}}', b""

    async def create_process(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = AgentBrowserClient(command=["agent-browser"])
    hostile_url = "https://example.com/?q=one%3Bwhoami%26two"

    await client.run("safe-session", "example.com", "open", hostile_url)

    assert captured["command"][-2:] == ("open", hostile_url)
    assert "shell" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_batch_passes_untrusted_urls_as_json_stdin(monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self, value):
            captured["stdin"] = value
            return b'[{"success":true,"result":{}},{"success":true,"result":{"closed":true}}]', b""

    async def create_process(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = AgentBrowserClient(command=["agent-browser"])
    hostile_url = "https://example.com/?q=one;whoami&two"

    await client.run_batch("safe-session", "example.com", [["open", hostile_url], ["close"]])

    assert captured["command"][-2:] == ("batch", "--json")
    assert json.loads(captured["stdin"]) == [["open", hostile_url], ["close"]]
    assert "shell" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_client_passes_untrusted_url_as_one_argv_element(monkeypatch):
    captured = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b'{"success":true,"data":{}}', b""

    async def create_process(*arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = AgentBrowserClient(command=["native-agent-browser"])
    hostile_url = "https://example.com/?q=& whoami | echo owned"
    await client.run("safe-session", "example.com", "open", hostile_url)

    assert captured["arguments"][-2:] == ("open", hostile_url)
    assert "shell" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_session_is_cleaned_up_after_navigation_failure():
    class FailingBrowser(FakeBrowser):
        async def run(self, session, host, *arguments):
            self.calls.append((session, host, arguments))
            if arguments[0] == "open":
                raise AgentBrowserError("failed")
            return {}

    client = FailingBrowser()
    gateway = BrowserGateway(client=client, resolver=public_resolver)
    result = await gateway.browser_read(["https://example.com/article"])
    assert result["pages"][0]["error"]["code"] == "navigation_failed"
    assert client.closed
