import asyncio
from typing import Any

import httpx

from app.core.config import get_settings


class LiteLLMGateway:
    """Management-plane client used to correlate harness traffic with model calls."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        settings = get_settings()
        if not settings.litellm_api_key:
            raise RuntimeError("LITELLM_API_KEY is required for every live agent harness")
        self.base_url = settings.litellm_base_url.rstrip("/")
        self.master_key = settings.litellm_api_key
        self.model = settings.litellm_model
        self.transport = transport

    async def create_trace_key(self, *, run_id: str, session_id: str, harness: str) -> str:
        payload = {
            "models": [self.model],
            "duration": "1h",
            "key_alias": f"trace-{session_id}",
            "metadata": {"run_id": run_id, "session_id": session_id, "harness": harness},
        }
        response = await self._request("POST", "/key/generate", json=payload)
        key = response.get("key")
        if not isinstance(key, str) or not key:
            raise RuntimeError("LiteLLM did not return a virtual trace key")
        return key

    async def spend_logs(self, api_key: str) -> list[dict[str, Any]]:
        """Wait briefly for LiteLLM's async spend writer, then return individual calls."""
        for delay in (0.0, 0.1, 0.25, 0.5, 1.0):
            if delay:
                await asyncio.sleep(delay)
            response = await self._request(
                "GET",
                "/spend/logs",
                params={"api_key": api_key, "summarize": "false"},
            )
            if isinstance(response, list) and response:
                return [item for item in response if isinstance(item, dict)]
        raise RuntimeError("LiteLLM returned no spend logs for the completed harness session")

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {self.master_key}"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=10,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
