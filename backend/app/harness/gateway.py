from typing import Any

import httpx

from app.core.config import get_settings


class LiteLLMGateway:
    """Management-plane client: issues the per-session key the harness calls models with."""

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
