from fastapi.testclient import TestClient

from app.main import app


def auth(client: TestClient, email: str = "learner@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "LearnerPass123!"})
    token = client.post("/auth/login", json={"email": email, "password": "LearnerPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_learning_run_persists_three_sessions_and_transcripts():
    with TestClient(app) as client:
        headers = auth(client)
        response = client.post("/learning-runs", headers=headers, json={"topic": "Python", "weeks": 3, "hours_per_week": 4, "provider": "mock"})
        assert response.status_code == 200
        run = response.json()
        assert len(run["sessions"]) == 3
        transcript = client.get(f"/agent-sessions/{run['sessions']['Researcher']}", headers=headers)
        assert transcript.status_code == 200
        assert transcript.json()["transcript"]
        resumed = client.post(f"/agent-sessions/{run['sessions']['Researcher']}/resume", headers=headers, json={"prompt": "Continue with one example."})
        assert resumed.status_code == 200
        closed = client.post(f"/agent-sessions/{run['sessions']['Researcher']}/close", headers=headers)
        assert closed.json()["status"] == "closed"
        assert client.post(f"/agent-sessions/{run['sessions']['Researcher']}/resume", headers=headers, json={"prompt": "Try again"}).status_code == 422


def test_analytics_is_admin_only():
    with TestClient(app) as client:
        learner_headers = auth(client, "not-admin@example.com")
        assert client.get("/analytics/overview", headers=learner_headers).status_code == 403
        admin_token = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        assert client.get("/analytics/overview", headers=headers).status_code == 200
        assert client.get("/analytics/users", headers=headers).status_code == 200
        assert client.get("/analytics/requests?status=completed", headers=headers).status_code == 200
        assert client.get("/analytics/sessions?provider=mock", headers=headers).status_code == 200
