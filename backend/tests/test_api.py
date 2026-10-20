from fastapi.testclient import TestClient

from app.main import app


def auth(client: TestClient, email: str = "learner@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
    token = client.post("/auth/login", json={"email": email, "password": "LearnerPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_analytics_is_admin_only():
    with TestClient(app) as client:
        learner_headers = auth(client, "not-admin@example.com")
        assert client.get("/analytics/overview", headers=learner_headers).status_code == 403
        admin_token = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        assert client.get("/analytics/overview", headers=headers).status_code == 200
        assert client.get("/analytics/users", headers=headers).status_code == 200
        assert client.get("/analytics/requests?status=completed", headers=headers).status_code == 200
        assert client.get("/analytics/sessions?harness=deep-agents", headers=headers).status_code == 200


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
