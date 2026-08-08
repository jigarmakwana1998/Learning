from fastapi.testclient import TestClient

from app.main import app


def auth(client: TestClient, email: str = "learner@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
    token = client.post("/auth/login", json={"email": email, "password": "LearnerPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_removed_offline_harness_is_rejected():
    with TestClient(app) as client:
        token = client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "AdminPass123!"},
        ).json()["access_token"]
        response = client.put(
            "/analytics/settings/agent-harness",
            headers={"Authorization": f"Bearer {token}"},
            json={"harness": "mock"},
        )
        assert response.status_code == 422


def test_analytics_is_admin_only():
    with TestClient(app) as client:
        learner_headers = auth(client, "not-admin@example.com")
        assert client.get("/analytics/overview", headers=learner_headers).status_code == 403
        admin_token = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        assert client.get("/analytics/overview", headers=headers).status_code == 200
        assert client.get("/analytics/users", headers=headers).status_code == 200
        assert client.get("/analytics/requests?status=completed", headers=headers).status_code == 200
        assert client.get("/analytics/sessions?harness=gemini-cli", headers=headers).status_code == 200
