import json
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt
from app.harness.gateway import LiteLLMGateway
from app.harness.deep_agents import DeepAgentRuntime, ToolInvocationEvent
from app.mcp.audit import new_session, record_trace_event
from app.models.database import AgentEvent
from app.schemas.learning import AgentHarness as AgentHarnessName


class AgentHarness:
    """Durable harness lifecycle with LiteLLM as the sole live model gateway."""

    def __init__(self, harness: AgentHarnessName, db: AsyncSession):
        self.harness, self.db = harness, db

    async def start_and_run(
        self,
        run_id: str,
        agent_name: str,
        prompt: str,
        *,
        persisted_prompt: str | None = None,
    ) -> tuple[AgentEvent, "AgentResult"]:
        session = new_session(run_id, agent_name, {"agent": agent_name})
        self.db.add(session)
        await self.db.flush()
        await record_trace_event(
            self.db,
            run_id=run_id,
            session_id=session.id,
            event_type="lifecycle",
            name="session.started",
            metadata={
                "agent": agent_name,
                "harness": self.harness,
                "model_gateway": "litellm",
            },
        )
        return session, await self.resume_and_run(
            session.id,
            prompt,
            persisted_prompt=persisted_prompt,
        )

    async def resume_and_run(
        self,
        session_id: str,
        prompt: str,
        *,
        persisted_prompt: str | None = None,
    ) -> "AgentResult":
        session = await self.get(session_id)
        if session.status == "closed":
            raise ValueError("A closed agent session cannot be resumed")
        durable_prompt = persisted_prompt if persisted_prompt is not None else prompt
        await self._append(session_id, "user", durable_prompt)
        started = perf_counter()
        await record_trace_event(
            self.db,
            run_id=session.run_id,
            session_id=session_id,
            event_type="harness",
            name="harness.request",
            input_payload={"prompt": durable_prompt},
            metadata={
                "harness": self.harness,
                "model_gateway": "litellm",
            },
        )
        try:
            # Model calls (prompts, responses, tokens, cost) live only in LiteLLM's spend
            # logs; they are tagged with run_id/session_id and read back by observability.
            gateway_api_key = await LiteLLMGateway().create_trace_key(
                run_id=session.run_id,
                session_id=session_id,
                harness=self.harness,
            )

            async def capture_harness_event(event: dict) -> None:
                payload = next(
                    (
                        candidate
                        for candidate in (event.get("item"), event.get("step"))
                        if isinstance(candidate, dict)
                    ),
                    event,
                )
                event_type = str(event.get("type") or event.get("event") or "harness.event")
                subtype = str(event.get("step_type") or payload.get("type") or "")
                event_name = ".".join(part for part in (event_type, subtype) if part)
                searchable = f"{event_name} {' '.join(str(key) for key in payload)}".lower()
                is_tool = any(marker in searchable for marker in ("tool", "command", "function", "mcp"))
                await record_trace_event(
                    self.db,
                    run_id=session.run_id,
                    session_id=session_id,
                    event_type="tool" if is_tool else "harness",
                    name=event_name,
                    status="failed" if "fail" in searchable or "error" in searchable else "completed",
                    input_payload=self._event_payload(payload, "input"),
                    output_payload=self._event_payload(payload, "output"),
                    metadata={"harness": self.harness, "raw_event": event},
                )

            execution = await DeepAgentRuntime().execute(
                prompt,
                session_id=session_id,
                run_id=session.run_id,
                agent_name=session.name,
                on_event=capture_harness_event,
                gateway_api_key=gateway_api_key,
            )
            for tool_event in execution.tool_events:
                await record_trace_event(
                    self.db,
                    run_id=session.run_id,
                    session_id=session_id,
                    event_type="tool",
                    name=tool_event.tool_name,
                    status="completed" if tool_event.status == "success" else "failed",
                    metadata=tool_event.metadata,
                    error=tool_event.error,
                    duration_ms=tool_event.duration_ms,
                )
            result = AgentResult(execution.payload, execution.tool_events, execution.visited_urls)
            session.output_payload = dict(result)
            session.status = "completed"
            await self._append(session_id, "assistant", json.dumps(dict(result)))
            await record_trace_event(
                self.db,
                run_id=session.run_id,
                session_id=session_id,
                event_type="harness",
                name="harness.response",
                output_payload=dict(result),
                metadata={
                    "harness": self.harness,
                    "model_gateway": "litellm",
                },
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return result
        except Exception as error:
            session.status, session.error_message = "failed", str(error)[:2000]
            await self._append(session_id, "system", f"Harness or model gateway failure: {error}")
            await record_trace_event(
                self.db,
                run_id=session.run_id,
                session_id=session_id,
                event_type="harness",
                name="harness.error",
                status="failed",
                error=str(error)[:2000],
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise
        finally:
            session.completed_at = datetime.now(timezone.utc)
            session.duration_ms = int((perf_counter() - started) * 1000)
            await self.db.flush()

    async def close(self, session_id: str) -> AgentEvent:
        session = await self.get(session_id)
        session.status, session.completed_at = "closed", datetime.now(timezone.utc)
        await self.db.flush()
        return session

    async def get(self, session_id: str) -> AgentEvent:
        session = await self.db.get(AgentEvent, session_id)
        if session is None or session.event_type != "session":
            raise KeyError("Agent session not found")
        return session

    async def _append(self, session_id: str, role: str, content: str) -> None:
        session = await self.get(session_id)
        await record_trace_event(
            self.db, run_id=session.run_id, session_id=session_id,
            event_type="message", name=role, content=encrypt(content),
        )

    @staticmethod
    def _event_payload(event: dict, direction: str) -> dict | None:
        keys = (
            ("input", "arguments", "args", "parameters", "command", "tool_name", "name")
            if direction == "input"
            else (
                "output",
                "result",
                "response",
                "aggregated_output",
                "content",
                "text",
                "stdout",
                "stderr",
                "exit_code",
            )
        )
        payload = {key: event[key] for key in keys if key in event}
        return payload or None

    async def record_tool(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        metadata: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Single audited entry point for MCP tool execution adapters."""
        session = await self.get(session_id)
        await record_trace_event(
            self.db,
            run_id=session.run_id,
            session_id=session_id,
            event_type="tool",
            name=tool_name,
            status="completed" if status == "success" else status,
            input_payload=(metadata or {}).get("input"),
            output_payload=(metadata or {}).get("output"),
            metadata=metadata,
            error=error,
        )


class AgentResult(dict):
    """A public payload with non-serialized evidence from its harness execution."""

    def __init__(
        self,
        payload: dict,
        tool_events: tuple[ToolInvocationEvent, ...] = (),
        visited_urls: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(payload)
        self.tool_events = tool_events
        self.visited_urls = visited_urls
