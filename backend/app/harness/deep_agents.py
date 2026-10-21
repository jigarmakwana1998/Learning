from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from deepagents import (
    GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile,
)
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware, SummarizationToolMiddleware
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.agents.researcher import SKILLS_DIR
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# The model gets our tools, read_file (to open a skill) and compact_conversation — no task subagent.
register_harness_profile(
    "litellm", HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False))
)


@dataclass(frozen=True)
class ToolInvocationEvent:
    tool_name: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class DeepAgentExecution:
    payload: dict[str, Any]
    tool_events: tuple[ToolInvocationEvent, ...] = ()
    visited_urls: frozenset[str] = field(default_factory=frozenset)


class AgentEventCollector(AsyncCallbackHandler):
    def __init__(self, on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None):
        self.on_event = on_event
        self.started: dict[UUID, tuple[str, float, dict[str, Any]]] = {}
        self.tool_events: list[ToolInvocationEvent] = []
        self.visited_urls: set[str] = set()
        self.activity: str | None = None

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        inputs: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        name = str((serialized or {}).get("name") or "tool")
        payload = self._safe_input(inputs or {"input": input_str})
        self.started[run_id] = (name, perf_counter(), payload)
        self.activity = f"{name} {json.dumps(payload, default=str)[:200]}"
        logger.info("tool.start %s input=%.300s", name, json.dumps(payload, default=str))

    async def on_tool_end(self, output: Any, *, run_id: UUID, **_: Any) -> None:
        name, started, payload = self.started.pop(run_id, ("tool", perf_counter(), {}))
        result = self._unwrap_tool_output(self._json_value(output))
        duration_ms = int((perf_counter() - started) * 1000)
        metadata = self._safe_metadata(name, payload, result)
        self._collect_urls(name, result)
        self.tool_events.append(ToolInvocationEvent(name, "success", metadata, duration_ms=duration_ms))
        logger.info("tool.end %s %dms output=%.300s", name, duration_ms, json.dumps(result, default=str))

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        name, started, payload = self.started.pop(run_id, ("tool", perf_counter(), {}))
        duration_ms = int((perf_counter() - started) * 1000)
        message = str(error)[:2000]
        logger.warning("tool.error %s %dms error=%.300s", name, duration_ms, message)
        self.tool_events.append(
            ToolInvocationEvent(name, "failed", {"input": payload}, error=message, duration_ms=duration_ms)
        )

    async def on_chat_model_start(self, serialized: dict[str, Any] | None, messages: list[list[Any]], *, run_id: UUID, **_: Any) -> None:
        self.started[run_id] = ("model", perf_counter(), {})
        logger.info("model.start messages=%d", sum(len(batch) for batch in messages))

    async def on_llm_end(self, response: Any, *, run_id: UUID, **_: Any) -> None:
        _, started, _ = self.started.pop(run_id, ("model", perf_counter(), {}))
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        logger.info("model.end %dms usage=%s", int((perf_counter() - started) * 1000), usage)

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        _, started, _ = self.started.pop(run_id, ("model", perf_counter(), {}))
        logger.warning("model.error %dms error=%.300s", int((perf_counter() - started) * 1000), error)

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        name: str | None = None,
        **_: Any,
    ) -> None:
        chain_name = name or str((serialized or {}).get("name") or "")
        if any(marker in chain_name.casefold() for marker in ("summar", "compact")):
            await self._emit({"type": "context.compaction.started", "name": chain_name})

    async def on_chain_end(self, outputs: dict[str, Any], *, name: str | None = None, **_: Any) -> None:
        if name and any(marker in name.casefold() for marker in ("summar", "compact")):
            await self._emit({"type": "context.compaction.completed", "name": name})

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            await self.on_event(event)

    def _collect_urls(self, name: str, output: Any) -> None:
        if "browser_read" not in name.casefold():
            return
        value = output
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return
        if not isinstance(value, dict):
            return
        for page in value.get("pages", []):
            if isinstance(page, dict) and str(page.get("status", "")).casefold() == "ok":
                for url in (page.get("url"), page.get("requested_url")):
                    if isinstance(url, str):
                        self.visited_urls.add(url)

    @staticmethod
    def _safe_input(payload: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in payload.items():
            if key.casefold() in {"content", "text", "body", "messages", "prompt", "input"}:
                continue
            if isinstance(value, str | int | float | bool) or value is None:
                safe[key] = value
            elif isinstance(value, list) and all(isinstance(item, str) for item in value):
                safe[key] = value[:20]
        return safe

    @staticmethod
    def _safe_metadata(name: str, payload: dict[str, Any], output: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {"input": payload}
        if not isinstance(output, dict):
            return metadata
        if "browser" in name.casefold():
            pages = output.get("pages") or output.get("results") or []
            if isinstance(pages, list):
                metadata["results"] = [
                    {
                        key: item[key]
                        for key in ("url", "title", "status")
                        if key in item and isinstance(item[key], str | int | float | bool)
                    }
                    for item in pages[:20]
                    if isinstance(item, dict)
                ]
                metadata["result_count"] = len(pages)
        return metadata

    @classmethod
    def _unwrap_tool_output(cls, value: Any) -> Any:
        if isinstance(value, dict) and "content" in value and "pages" not in value:
            return cls._unwrap_tool_output(value["content"])
        if isinstance(value, list) and len(value) == 1:
            item = value[0]
            if isinstance(item, dict) and "text" in item:
                return cls._unwrap_tool_output(item["text"])
        if isinstance(value, str):
            try:
                return cls._unwrap_tool_output(json.loads(value))
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict | list | str | int | float | bool) or value is None:
            return value
        return str(value)


class DeepAgentRuntime:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def execute(
        self,
        prompt: str,
        *,
        session_id: str,
        run_id: str,
        agent_name: str,
        gateway_api_key: str,
        system_prompt: str,
        tools: list[BaseTool] | None = None,
        collector: AgentEventCollector | None = None,
        on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> DeepAgentExecution:
        metadata = {
            "run_id": run_id,
            "session_id": session_id,
            "agent_role": agent_name,
            "harness": "deep-agents",
            "requested_reasoning_effort": self.settings.agent_reasoning_effort,
        }
        model = self._model(gateway_api_key, metadata)
        # Skills are read from disk; everything else (e.g. evicted large tool results) stays in state.
        backend = CompositeBackend(
            default=StateBackend(),
            routes={"/skills/": FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)},
        )
        summarization = SummarizationMiddleware(
            model,
            backend=backend,
            trigger=("tokens", self.settings.agent_compaction_tokens),
            keep=("messages", self.settings.agent_compaction_keep_messages),
            trim_tokens_to_summarize=self.settings.agent_summary_input_tokens,
        )
        middleware = [
            FilesystemMiddleware(backend=backend, tools=["read_file"]),
            summarization,
            SummarizationToolMiddleware(summarization),
        ]
        collector = collector or AgentEventCollector()
        collector.on_event = on_event

        async with self._checkpointer() as checkpointer:
            agent = create_deep_agent(
                model=model,
                tools=tools or [],
                system_prompt=system_prompt,
                middleware=middleware,
                backend=backend,
                skills=["/skills/"],
                checkpointer=checkpointer,
                name=agent_name.casefold().replace("_", "-"),
            )
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={
                    "configurable": {"thread_id": session_id},
                    "metadata": metadata,
                    "callbacks": [collector],
                    "recursion_limit": self.settings.agent_recursion_limit,
                },
            )

        payload = self._payload(result)
        return DeepAgentExecution(payload, tuple(collector.tool_events), frozenset(collector.visited_urls))

    def _model(self, api_key: str, metadata: dict[str, Any]) -> ChatLiteLLM:
        provider_effort = (
            "high"
            if self.settings.agent_reasoning_effort == "medium"
            else self.settings.agent_reasoning_effort
        )
        return ChatLiteLLM(
            model=f"litellm_proxy/{self.settings.litellm_model}",
            api_base=self.settings.litellm_base_url.rstrip("/"),
            api_key=api_key,
            max_retries=2,
            extra_headers={
                "x-litellm-tags": "harness,deepagents",
                "x-litellm-spend-logs-metadata": json.dumps(metadata),
            },
            model_kwargs={
                "reasoning_effort": provider_effort,
                "extra_body": {"chat_template_kwargs": {"clear_thinking": True}},
            },
        )

    @asynccontextmanager
    async def _checkpointer(self) -> AsyncIterator[BaseCheckpointSaver]:
        database_url = self.settings.agent_checkpoint_database_url
        if database_url.startswith(("postgresql+asyncpg://", "postgres+asyncpg://")):
            database_url = database_url.replace("+asyncpg", "", 1)
        if database_url.startswith(("postgresql://", "postgres://")):
            async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
                await saver.setup()
                yield saver
            return
        sqlite_path = self._sqlite_path(database_url)
        async with AsyncSqliteSaver.from_conn_string(sqlite_path) as saver:
            await saver.setup()
            yield saver

    @staticmethod
    def _sqlite_path(database_url: str) -> str:
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if database_url.startswith(prefix):
                return str(Path(database_url.removeprefix(prefix)))
        if database_url in {"sqlite+aiosqlite:///:memory:", "sqlite:///:memory:", ":memory:"}:
            return ":memory:"
        raise ValueError("AGENT_CHECKPOINT_DATABASE_URL must use PostgreSQL or SQLite")

    @staticmethod
    def _payload(result: dict[str, Any]) -> dict[str, Any]:
        messages = result.get("messages", [])
        content = next(
            (message.content for message in reversed(messages) if isinstance(message, AIMessage)),
            "",
        )
        return {"message": content if isinstance(content, str) else str(content)}
