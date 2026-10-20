from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import get_settings


async def request(
    method: str,
    path: str,
    *,
    access_token: str | None = None,
    api_key: str | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    settings = get_settings()
    headers = {"apikey": api_key or settings.supabase_publishable_key}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        async with httpx.AsyncClient(base_url=settings.supabase_url, timeout=10) as client:
            return await client.request(method, path, headers=headers, json=json, params=params)
    except httpx.RequestError as error:
        raise HTTPException(status_code=502, detail="Authentication service unavailable") from error


async def grant_admin(subject: str) -> None:
    """Store the admin role in Supabase app_metadata, which only the secret key may write."""
    response = await request(
        "PUT",
        f"/auth/v1/admin/users/{subject}",
        api_key=get_settings().supabase_secret_key,
        json={"app_metadata": {"role": "admin"}},
    )
    if not response.is_success:
        raise HTTPException(status_code=502, detail="Could not grant the configured admin role")
