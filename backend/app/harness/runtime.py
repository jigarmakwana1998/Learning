import json
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt
from app.harness.providers.factory import get_runtime
from app.harness.providers.cli import ProviderExecution, ToolInvocationEvent
from app.mcp.audit import record_tool_invocation
from app.models.database import AgentSessionRecord, TranscriptEntryRecord
from app.schemas.learning import AgentProvider


class AgentHarness:
    """Durable lifecycle: provider execution, transcript append, resume, and close."""
    def __init__(self, provider: AgentProvider, db: AsyncSession):
        self.provider, self.db = provider, db

    async def start_and_run(self, run_id: str, agent_name: str, prompt: str) -> tuple[AgentSessionRecord, "AgentResult"]:
        session = AgentSessionRecord(agent_run_id=run_id, agent_name=agent_name, provider=self.provider, input_payload={"agent": agent_name})
        self.db.add(session)
        await self.db.flush()
        return session, await self.resume_and_run(session.id, prompt)

    async def resume_and_run(self, session_id: str, prompt: str) -> "AgentResult":
        session = await self.get(session_id)
        if session.status == "closed": raise ValueError("A closed agent session cannot be resumed")
        await self._append(session_id, "user", prompt)
        started = perf_counter()
        try:
            raw_execution = await get_runtime(self.provider, session.agent_name).execute(prompt)
            execution = raw_execution if isinstance(raw_execution, ProviderExecution) else ProviderExecution(raw_execution)
            for tool_event in execution.tool_events:
                await record_tool_invocation(
                    self.db, session_id, tool_event.tool_name, tool_event.status,
                    tool_event.metadata, tool_event.error, duration_ms=tool_event.duration_ms,
                )
            result = AgentResult(execution.payload, execution.tool_events, execution.visited_urls)
            session.output_payload = dict(result)
            session.status = "completed"
            await self._append(session_id, "assistant", json.dumps(dict(result)))
            return result
        except Exception as error:
            session.status, session.error_message = "failed", str(error)[:2000]
            await self._append(session_id, "system", f"Provider failure: {error}")
            raise
        finally:
            session.completed_at = datetime.now(timezone.utc)
            session.duration_ms = int((perf_counter() - started) * 1000)
            await self.db.flush()

    async def close(self, session_id: str) -> AgentSessionRecord:
        session = await self.get(session_id)
        session.status, session.completed_at = "closed", datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def get(self, session_id: str) -> AgentSessionRecord:
        session = await self.db.get(AgentSessionRecord, session_id)
        if session is None: raise KeyError("Agent session not found")
        return session

    async def _append(self, session_id: str, role: str, content: str) -> None:
        sequence = (await self.db.scalar(select(func.coalesce(func.max(TranscriptEntryRecord.sequence), 0)).where(TranscriptEntryRecord.session_id == session_id))) + 1
        self.db.add(TranscriptEntryRecord(session_id=session_id, sequence=sequence, role=role, encrypted_content=encrypt(content)))
        await self.db.flush()

    async def record_tool(self, session_id: str, tool_name: str, status: str, metadata: dict | None = None, error: str | None = None) -> None:
        """Single auditable entry point for future MCP tool execution adapters."""
        await record_tool_invocation(self.db, session_id, tool_name, status, metadata, error)


class AgentResult(dict):
    """A public payload with non-serialized evidence from its provider execution."""

    def __init__(
        self,
        payload: dict,
        tool_events: tuple[ToolInvocationEvent, ...] = (),
        visited_urls: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(payload)
        self.tool_events = tool_events
        self.visited_urls = visited_urls
