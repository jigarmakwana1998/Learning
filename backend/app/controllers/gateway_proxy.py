import ipaddress

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.config import get_settings

router = APIRouter(tags=["internal"])
_HOP_BY_HOP = {"connection", "content-length", "host", "transfer-encoding"}
http_client_factory = httpx.AsyncClient


@router.api_route(
    "/internal/litellm/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_gemini_to_litellm(path: str, request: Request) -> StreamingResponse:
    """Give Gemini CLI a loopback URL while LiteLLM remains a Compose sidecar."""
    client_host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=404, detail="Not found")

    upstream_url = f"{get_settings().litellm_base_url.rstrip('/')}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.casefold() not in _HOP_BY_HOP
    }
    client = http_client_factory(timeout=None)
    upstream_request = client.build_request(
        request.method,
        upstream_url,
        headers=headers,
        content=await request.body(),
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except Exception:
        await client.aclose()
        raise

    async def close_upstream() -> None:
        await upstream.aclose()
        await client.aclose()

    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.casefold() not in _HOP_BY_HOP
    }
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(close_upstream),
    )
