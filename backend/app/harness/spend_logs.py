"""Read model calls straight from LiteLLM's spend log table (same database, never copied)."""

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

# Owned and migrated by the LiteLLM proxy (litellm/proxy/schema.prisma). The harness tags
# every call through `x-litellm-spend-logs-metadata`, stored under metadata.spend_logs_metadata.
spend_logs = sa.table(
    "LiteLLM_SpendLogs",
    *(sa.column(name) for name in ("request_id", "call_type", "model", "model_group", "custom_llm_provider", "api_base", "cache_hit", "status")),
    sa.column("metadata", JSONB), sa.column("messages", JSONB), sa.column("response", JSONB),
    sa.column("prompt_tokens", sa.Integer), sa.column("completion_tokens", sa.Integer),
    sa.column("spend", sa.Float), sa.column("request_duration_ms", sa.Integer),
    sa.column("startTime", sa.DateTime(timezone=True)), sa.column("endTime", sa.DateTime(timezone=True)),
)
tags = spend_logs.c.metadata["spend_logs_metadata"]


async def _available(db: AsyncSession, run_ids: list[str]) -> bool:
    if not run_ids or db.get_bind().dialect.name != "postgresql":
        return False
    return await db.scalar(sa.select(sa.func.to_regclass('"LiteLLM_SpendLogs"'))) is not None


async def model_calls(db: AsyncSession, run_ids: list[str]) -> list[dict[str, Any]]:
    """Model-call trace events for the given runs; empty when LiteLLM's table is unavailable."""
    if not await _available(db, run_ids):
        return []
    rows = (await db.execute(sa.select(spend_logs).where(tags["run_id"].astext.in_(run_ids)).order_by(spend_logs.c.startTime))).mappings()
    return [model_event(dict(row)) for row in rows]


async def model_call_totals(db: AsyncSession, run_ids: list[str]) -> dict[str, tuple[int, float]]:
    """(call count, total spend) per run without loading prompts or responses."""
    if not await _available(db, run_ids):
        return {}
    run_id = tags["run_id"].astext
    rows = await db.execute(sa.select(run_id, sa.func.count(), sa.func.coalesce(sa.func.sum(spend_logs.c.spend), 0)).where(run_id.in_(run_ids)).group_by(run_id))
    return {key: (int(count), float(spend)) for key, count, spend in rows}


def model_event(log: dict[str, Any]) -> dict[str, Any]:
    """Map one spend-log row onto the trace event shape the run explorer renders."""
    tag = (log.get("metadata") or {}).get("spend_logs_metadata") or {}
    start, end = log.get("startTime"), log.get("endTime")
    duration = log.get("request_duration_ms")
    if duration is None and isinstance(start, datetime) and isinstance(end, datetime):
        duration = int((end - start).total_seconds() * 1000)
    # Research agents read untrusted page bodies; those live in source_snapshots, not here.
    redacted = str(tag.get("agent_role") or "").startswith("Research")
    return {
        "id": log["request_id"],
        "run_id": tag.get("run_id"),
        "session_id": tag.get("session_id"),
        "sequence": 0,
        "event_type": "model",
        "name": f"litellm.{log.get('call_type') or 'completion'}",
        "status": "failed" if str(log.get("status")).lower() in {"failed", "failure", "error"} else "completed",
        "input_payload": {"redacted": True, "reason": "ephemeral research evidence"} if redacted else {"messages": log.get("messages")},
        "output_payload": log.get("response") if isinstance(log.get("response"), dict) else {"response": log.get("response")},
        "metadata": {key: log[key] for key in ("request_id", "call_type", "model", "model_group", "custom_llm_provider", "api_base", "cache_hit") if log.get(key)},
        "error_message": None,
        "duration_ms": duration,
        "prompt_tokens": log.get("prompt_tokens"),
        "completion_tokens": log.get("completion_tokens"),
        "total_cost_usd": log.get("spend"),
        "created_at": start,
    }
