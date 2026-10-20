"""Auth contract tests against the real Supabase project, so API drift fails here, not in prod."""

import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import supabase
from app.core.config import get_settings
from app.main import app

real_request = supabase.request


@pytest.fixture
def live(monkeypatch, fake_supabase, live_supabase_credentials):
    creds = live_supabase_credentials
    if not all(creds.values()):
        if os.getenv("CI"):
            pytest.fail("SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and SUPABASE_SECRET_KEY secrets are required")
        pytest.skip("Live Supabase credentials are not configured")
    monkeypatch.setattr(supabase, "request", real_request)
    for key, value in creds.items():
        monkeypatch.setenv(key, value)
    admin = httpx.Client(base_url=creds["SUPABASE_URL"], headers={"apikey": creds["SUPABASE_SECRET_KEY"]}, timeout=10)
    email, password = f"contract-{uuid4().hex}@example.com", f"Pw-{uuid4().hex}!"
    created = admin.post("/auth/v1/admin/users", json={"email": email, "password": password, "email_confirm": True})
    assert created.status_code == 200, created.text
    monkeypatch.setenv("ADMIN_EMAIL", email)
    get_settings.cache_clear()
    yield email, password
    get_settings.cache_clear()
    admin.delete(f"/auth/v1/admin/users/{created.json()['id']}").raise_for_status()
    admin.close()


def test_live_supabase_login_me_and_admin_promotion(live):
    email, password = live
    with TestClient(app) as client:
        assert client.post("/auth/login", json={"email": email, "password": "WrongPass123!"}).status_code == 401
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        assert login.json()["role"] == "learner"
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        assert me.json()["email"] == email and me.json()["role"] == "admin"
        # The promotion must persist in Supabase app_metadata, not only locally.
        assert client.post("/auth/login", json={"email": email, "password": password}).json()["role"] == "admin"
        assert client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
