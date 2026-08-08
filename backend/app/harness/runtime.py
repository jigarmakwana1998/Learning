import json
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt
from app.harness.gateway import LiteLLMGateway
from app.harness.providers.cli import ProviderExecution, ToolInvocationEvent
from app.harness.providers.factory import get_runtime
from app.mcp.audit import record_tool_invocation, record_trace_event
from app.models.database import AgentSessionRecord, TranscriptEntryRecord
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
    ) -> tuple[AgentSessionRecord, "AgentResult"]:
        session = AgentSessionRecord(
            agent_run_id=run_id,
            agent_name=agent_name,
            harness=self.harness,
            input_payload={"agent": agent_name},
        )
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
            run_id=session.agent_run_id,
            session_id=session_id,
            event_type="harness",
            name="harness.request",
            input_payload={"prompt": durable_prompt},
            metadata={
                "harness": self.harness,
                "model_gateway": "litellm",
            },
        )
        gateway = None
        gateway_api_key = None
        try:
            gateway = LiteLLMGateway()
            gateway_api_key = await gateway.create_trace_key(
                run_id=session.agent_run_id,
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
                    run_id=session.agent_run_id,
                    session_id=session_id,
                    event_type="tool" if is_tool else "harness",
                    name=event_name,
                    status="failed" if "fail" in searchable or "error" in searchable else "completed",
                    input_payload=self._event_payload(payload, "input"),
                    output_payload=self._event_payload(payload, "output"),
                    metadata={"harness": self.harness, "raw_event": event},
                )

            raw_execution = await get_runtime(self.harness, session.agent_name).execute(
                prompt,
                on_event=capture_harness_event,
                gateway_api_key=gateway_api_key,
            )
            execution = (
                raw_execution
                if isinstance(raw_execution, ProviderExecution)
                else ProviderExecution(raw_execution)
            )
            for tool_event in execution.tool_events:
                await record_tool_invocation(
                    self.db,
                    session_id,
                    tool_event.tool_name,
                    tool_event.status,
                    tool_event.metadata,
                    tool_event.error,
                    duration_ms=tool_event.duration_ms,
                )
                await record_trace_event(
                    self.db,
                    run_id=session.agent_run_id,
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
                run_id=session.agent_run_id,
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
                run_id=session.agent_run_id,
                session_id=session_id,
                event_type="harness",
                name="harness.error",
                status="failed",
                error=str(error)[:2000],
                duration_ms=int((perf_counter() - started) * 1000),
            )
            raise
        finally:
            if gateway and gateway_api_key:
                try:
                    await self._record_model_events(
                        session,
                        await gateway.spend_logs(gateway_api_key),
                        redact_input=persisted_prompt is not None,
                    )
                except Exception as telemetry_error:
                    await record_trace_event(
                        self.db,
                        run_id=session.agent_run_id,
                        session_id=session_id,
                        event_type="lifecycle",
                        name="litellm.trace_sync_failed",
                        status="failed",
                        metadata={"harness": self.harness},
                        error=str(telemetry_error)[:2000],
                    )
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
        if session is None:
            raise KeyError("Agent session not found")
        return session

    async def _append(self, session_id: str, role: str, content: str) -> None:
        sequence = (
            await self.db.scalar(
                select(func.coalesce(func.max(TranscriptEntryRecord.sequence), 0)).where(
                    TranscriptEntryRecord.session_id == session_id
                )
            )
        ) + 1
        self.db.add(
            TranscriptEntryRecord(
                session_id=session_id,
                sequence=sequence,
                role=role,
                encrypted_content=encrypt(content),
            )
        )
        await self.db.flush()

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

    async def _record_model_events(
        self,
        session: AgentSessionRecord,
        logs: list[dict],
        *,
        redact_input: bool = False,
    ) -> None:
        for log in logs:
            proxy_request = log.get("proxy_server_request")
            request_body = proxy_request.get("body") if isinstance(proxy_request, dict) else None
            messages = log.get("messages")
            input_payload = {"messages": messages} if messages is not None else request_body
            if input_payload is not None and not isinstance(input_payload, dict):
                input_payload = {"request": input_payload}
            if redact_input and input_payload is not None:
                input_payload = {"redacted": True, "reason": "ephemeral research evidence"}
            response = log.get("response")
            output_payload = response if isinstance(response, dict) else {"response": response}
            if response is None:
                output_payload = None
            metadata = {
                key: log.get(key)
                for key in (
                    "request_id",
                    "call_type",
                    "model",
                    "model_group",
                    "custom_llm_provider",
                    "api_base",
                    "cache_hit",
                )
                if log.get(key) is not None
            }
            await record_trace_event(
                self.db,
                run_id=session.agent_run_id,
                session_id=session.id,
                event_type="model",
                name=f"litellm.{log.get('call_type') or 'completion'}",
                status=self._model_status(log.get("status")),
                input_payload=input_payload,
                output_payload=output_payload,
                metadata=metadata,
                duration_ms=self._model_duration(log),
                prompt_tokens=self._as_int(log.get("prompt_tokens")),
                completion_tokens=self._as_int(log.get("completion_tokens")),
                total_cost_usd=self._as_float(log.get("spend")),
                created_at=self._timestamp(log.get("startTime")),
            )

    @staticmethod
    def _model_status(status: object) -> str:
        return "failed" if str(status).lower() in {"failed", "failure", "error"} else "completed"

    @staticmethod
    def _as_int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def _model_duration(cls, log: dict) -> int | None:
        explicit = cls._as_int(log.get("request_duration_ms"))
        if explicit is not None:
            return explicit
        start, end = cls._timestamp(log.get("startTime")), cls._timestamp(log.get("endTime"))
        return int((end - start).total_seconds() * 1000) if start and end else None

    async def record_tool(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        metadata: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Single audited entry point for MCP tool execution adapters."""
        await record_tool_invocation(self.db, session_id, tool_name, status, metadata, error)
        session = await self.get(session_id)
        await record_trace_event(
            self.db,
            run_id=session.agent_run_id,
            session_id=session_id,
            event_type="tool",
            name=tool_name,
            status=status,
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
