import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models.database import AgentRun, AgentSessionRecord, AgentTraceEvent, LearningRequest, User


def _auth(client: TestClient) -> dict[str, str]:
    client.post("/auth/register", json={"email": "trace@example.com", "password": "LearnerPass123!"})
    token = client.post("/auth/login", json={"email": "trace@example.com", "password": "LearnerPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_trace() -> str:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "trace@example.com"))
        request = LearningRequest(user_id=user.id, topic="Tracing", level="beginner", weeks=2, hours_per_week=4)
        db.add(request)
        await db.flush()
        run = AgentRun(learning_request_id=request.id, harness="gemini-cli", status="completed")
        db.add(run)
        await db.flush()

        for agent_name in ("researcher", "planner", "assessment"):
            session = AgentSessionRecord(
                agent_run_id=run.id,
                agent_name=agent_name,
                harness="gemini-cli",
                status="completed",
            )
            db.add(session)
            await db.flush()
            db.add_all([
                AgentTraceEvent(
                    run_id=run.id,
                    session_id=session.id,
                    sequence=1,
                    event_type="model",
                    name="harness.request",
                    input_payload={"prompt": agent_name},
                ),
                AgentTraceEvent(
                    run_id=run.id,
                    session_id=session.id,
                    sequence=2,
                    event_type="model",
                    name="harness.response",
                    output_payload={"agent": agent_name},
                ),
            ])

        await db.commit()
        return run.id


def test_run_trace_exposes_model_boundaries_for_the_owner():
    with TestClient(app) as client:
        headers = _auth(client)
        run_id = asyncio.run(_seed_trace())
        runs = client.get("/observability/runs", headers=headers)
        assert runs.status_code == 200
        assert runs.json()[0]["id"] == run_id
        trace = client.get(f"/observability/runs/{run_id}", headers=headers)
        assert trace.status_code == 200
        body = trace.json()
        assert len(body["sessions"]) == 3
        assert body["harness"] == "gemini-cli"
        assert any(event["name"] == "harness.request" for event in body["events"])
        assert any(event["name"] == "harness.response" for event in body["events"])
        assert all("input_payload" in event for event in body["events"])
