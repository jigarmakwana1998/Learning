from fastapi.testclient import TestClient

from app.main import app


def auth(client: TestClient, email: str = "learner@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
    token = client.post("/auth/login", json={"email": email, "password": "LearnerPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_rejects_invalid_supabase_credentials():
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"email": "missing@example.com", "password": "WrongPass123!"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid login credentials"


def test_registration_reports_required_email_confirmation(fake_supabase):
    fake_supabase.require_email_confirmation = True
    with TestClient(app) as client:
        response = client.post("/auth/register", json={"email": "confirm@example.com", "password": "LearnerPass123!"})
    assert response.status_code == 201
    assert response.json()["access_token"] is None
    assert response.json()["message"] == "Check your inbox to confirm your email, then sign in."


def test_configured_admin_email_is_promoted_in_supabase(fake_supabase):
    with TestClient(app) as client:
        token = client.post("/auth/register", json={"email": "Owner@example.com", "password": "OwnerPass123!"}).json()["access_token"]
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["role"] == "admin"
    assert fake_supabase.users["owner@example.com"]["app_metadata"] == {"role": "admin"}


def test_failed_background_run_reports_its_reason(monkeypatch):
    from contextlib import asynccontextmanager

    from app.services.research_service import research_service

    @asynccontextmanager
    async def unavailable_browser():
        raise RuntimeError("The browser MCP server could not start.")
        yield []

    monkeypatch.setattr(research_service, "browser_tools", unavailable_browser)
    with TestClient(app) as client:
        headers = auth(client, "async-runner@example.com")
        started = client.post("/research-runs", headers=headers, json={"topic": "Transformers", "weeks": 1})
        assert started.status_code == 202 and started.json()["status"] == "running"
        run = client.get(f"/research-runs/{started.json()['id']}", headers=headers).json()
        assert run["status"] == "failed"
        assert run["error"] == "The browser MCP server could not start."
