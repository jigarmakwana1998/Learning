import pytest
from fastapi import HTTPException, Request

import app.controllers.gateway_proxy as gateway_proxy
from app.core.config import get_settings


def request_for(client_host: str) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b'{"contents":[]}', "more_body": False}

    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "client": (client_host, 12345),
        "path": "/internal/litellm/v1beta/models/agent-model:streamGenerateContent",
        "query_string": b"alt=sse",
        "headers": [(b"x-goog-api-key", b"sk-session")],
    }, receive)


@pytest.mark.asyncio
async def test_loopback_bridge_streams_gemini_protocol_to_litellm(monkeypatch):
    captured = {}

    class Upstream:
        status_code = 200
        headers = {"content-type": "text/event-stream", "connection": "keep-alive"}

        async def aiter_raw(self):
            yield b"data: done\n\n"

        async def aclose(self):
            captured["upstream_closed"] = True

    class Client:
        def __init__(self, **kwargs):
            captured["client_options"] = kwargs

        def build_request(self, method, url, **kwargs):
            captured.update(method=method, url=url, request_options=kwargs)
            return object()

        async def send(self, _request, *, stream):
            assert stream is True
            return Upstream()

        async def aclose(self):
            captured["client_closed"] = True

    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm:4000")
    get_settings.cache_clear()
    monkeypatch.setattr(gateway_proxy, "http_client_factory", Client)
    response = await gateway_proxy.proxy_gemini_to_litellm(
        "v1beta/models/agent-model:streamGenerateContent",
        request_for("127.0.0.1"),
    )
    body = b"".join([chunk async for chunk in response.body_iterator])
    await response.background()

    assert captured["url"] == "http://litellm:4000/v1beta/models/agent-model:streamGenerateContent?alt=sse"
    assert captured["request_options"]["headers"]["x-goog-api-key"] == "sk-session"
    assert body == b"data: done\n\n"
    assert captured["upstream_closed"] is True
    assert captured["client_closed"] is True
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_bridge_is_not_exposed_to_non_loopback_clients():
    with pytest.raises(HTTPException) as raised:
        await gateway_proxy.proxy_gemini_to_litellm("v1beta/models/model", request_for("172.20.0.10"))
    assert raised.value.status_code == 404
