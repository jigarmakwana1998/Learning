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


def test_old_research_activity_is_available_only_to_its_owner():
    from sqlalchemy import select
    from learning_db.models import AgentRun, AgentSessionRecord, Course, LearningRequest, McpToolInvocation, SourcePage, User
    from learning_db.session import SessionLocal

    async def seed():
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == "history@example.com"))
            request = LearningRequest(user_id=user.id, topic="Saved topic", level="beginner", hours_per_week=5, weeks=4)
            db.add(request)
            await db.flush()
            run = AgentRun(learning_request_id=request.id, harness="deep-agents", status="completed", result={})
            db.add(run)
            await db.flush()
            session = AgentSessionRecord(agent_run_id=run.id, agent_name="Researcher", harness="deep-agents", status="completed")
            db.add(session)
            await db.flush()
            db.add(McpToolInvocation(session_id=session.id, tool_name="browser_search", status="success", metadata_json={"input": {"query": "old query"}, "results": [{"url": "https://example.com", "title": "Example"}]}))
            db.add(McpToolInvocation(session_id=session.id, tool_name="browser_read", status="success", metadata_json={"input": {"urls": ["https://example.com"]}, "results": [{"url": "https://example.com", "title": "Example"}]}))
            db.add(SourcePage(research_run_id=run.id, position=1, url="https://example.com", title="Example", text="Saved page text"))
            course_run = AgentRun(learning_request_id=request.id, harness="deep-agents", status="completed", result={})
            db.add(course_run)
            await db.flush()
            db.add(Course(id=course_run.id, research_run_id=run.id, version=1, chapters=[], sections={}))
            await db.commit()
            return run.id, course_run.id

    with TestClient(app) as client:
        owner = auth(client, "history@example.com")
        client.get("/auth/me", headers=owner)
        run_id, course_id = client.portal.call(seed)
        activity = client.get(f"/research-runs/{run_id}/activity", headers=owner).json()
        assert activity["sessions"][0]["activity"][0]["input"]["query"] == "old query"
        assert activity["sessions"][0]["activity"][0]["output"]["results"][0]["url"] == "https://example.com"
        assert activity["sessions"][0]["activity"][1]["output"]["results"][0]["content"] == "Saved page text"
        assert any(item["id"] == run_id for item in client.get("/research-runs", headers=owner).json())
        assert client.get(f"/research-runs/{run_id}/courses", headers=owner).json()[0]["id"] == course_id
        assert client.get(f"/courses/{course_id}", headers=owner).json()["sources"][0]["title"] == "Example"
        other = auth(client, "other-history@example.com")
        assert client.get(f"/research-runs/{run_id}/activity", headers=other).status_code == 404
        assert client.get(f"/courses/{course_id}", headers=other).status_code == 404


def test_interrupted_course_keeps_its_version_specific_sources():
    from uuid import uuid4

    from sqlalchemy import select
    from learning_db.models import AgentRun, Course, LearningRequest, SourcePage, User
    from learning_db.session import SessionLocal

    email = f"restart-{uuid4().hex}@example.com"

    async def seed():
        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == email))
            request = LearningRequest(user_id=user.id, topic="Functions", level="beginner", hours_per_week=1, weeks=1)
            db.add(request)
            await db.flush()
            research = AgentRun(learning_request_id=request.id, harness="deep-agents", status="completed", result={})
            db.add(research)
            await db.flush()
            run = AgentRun(learning_request_id=request.id, harness="deep-agents", result={"source_snapshot": True})
            db.add(run)
            await db.flush()
            db.add(Course(id=run.id, research_run_id=research.id, version=1, chapters=[], sections={}))
            db.add(SourcePage(research_run_id=run.id, position=1, url="https://example.com/new",
                              title="New evidence", text="Version-specific evidence"))
            await db.commit()
            return run.id

    with TestClient(app) as client:
        owner = auth(client, email)
        client.get("/auth/me", headers=owner)
        course_id = client.portal.call(seed)
    with TestClient(app) as client:
        course = client.get(f"/courses/{course_id}", headers=owner).json()
    assert course["status"] == "failed" and "restart" in course["error"]
    assert course["sources"] == [{"id": "s1", "url": "https://example.com/new", "title": "New evidence"}]
