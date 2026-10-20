import json
import os
from functools import lru_cache
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def json_environment(name: str) -> dict[str, dict[str, Any]] | None:
    raw = os.getenv(name)
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(isinstance(item, dict) for item in value.values()):
        raise RuntimeError(f"{name} must be a JSON object of MCP server configurations")
    return value


class Settings(BaseModel):
    app_name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Learning Coach API"))
    app_version: str = Field(default_factory=lambda: os.getenv("APP_VERSION", "0.4.0"))
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_reasoning_effort: Literal["low", "medium", "high", "max"] = Field(
        default_factory=lambda: os.getenv("AGENT_REASONING_EFFORT", "medium")
    )
    agent_recursion_limit: int = Field(default_factory=lambda: int(os.getenv("AGENT_RECURSION_LIMIT", "100")))
    agent_compaction_tokens: int = Field(
        default_factory=lambda: int(os.getenv("AGENT_COMPACTION_TOKENS", "838860"))
    )
    agent_compaction_keep_messages: int = Field(
        default_factory=lambda: int(os.getenv("AGENT_COMPACTION_KEEP_MESSAGES", "20"))
    )
    agent_summary_input_tokens: int = Field(
        default_factory=lambda: int(os.getenv("AGENT_SUMMARY_INPUT_TOKENS", "32000"))
    )
    agent_checkpoint_database_url: str = Field(
        default_factory=lambda: os.getenv("AGENT_CHECKPOINT_DATABASE_URL")
        or os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./learning_coach.db")
    )
    agent_mcp_enabled: bool = Field(
        default_factory=lambda: os.getenv("AGENT_MCP_ENABLED", "true").casefold() == "true"
    )
    agent_mcp_roles: set[str] = Field(
        default_factory=lambda: {
            role.strip() for role in os.getenv("AGENT_MCP_ROLES", "Researcher").split(",") if role.strip()
        }
    )
    mcp_servers: dict[str, dict[str, Any]] | None = Field(
        default_factory=lambda: json_environment("MCP_SERVERS_JSON")
    )
    litellm_base_url: str = Field(default_factory=lambda: os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    litellm_api_key: str | None = Field(default_factory=lambda: os.getenv("LITELLM_API_KEY") or None)
    litellm_model: str = Field(default_factory=lambda: os.getenv("LITELLM_MODEL", "agent-model"))
    database_url: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./learning_coach.db"))
    jwt_secret: str = Field(default_factory=lambda: os.getenv("JWT_SECRET", "change-this-development-jwt-secret"))
    encryption_key: str = Field(default_factory=lambda: required_environment("APP_ENCRYPTION_KEY"))
    cors_origins: list[str] = Field(default_factory=lambda: [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8081,http://localhost:19006").split(",") if origin.strip()])
    admin_email: str = Field(default_factory=lambda: os.getenv("ADMIN_EMAIL", "admin@example.com"))
    admin_password: str = Field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "change-me-now"))
    research_max_searches: int = Field(default_factory=lambda: int(os.getenv("RESEARCH_MAX_SEARCHES", "20")))
    research_max_pages: int = Field(default_factory=lambda: int(os.getenv("RESEARCH_MAX_PAGES", "40")))
    research_max_actions: int = Field(default_factory=lambda: int(os.getenv("RESEARCH_MAX_ACTIONS", "60")))
    research_max_elapsed_seconds: int = Field(
        default_factory=lambda: int(os.getenv("RESEARCH_MAX_ELAPSED_SECONDS", "600"))
    )
    local_auth: bool = Field(default_factory=lambda: os.getenv("LOCAL_AUTH", "false").casefold() == "true")
    supabase_url: str | None = Field(default_factory=lambda: None if os.getenv("LOCAL_AUTH", "false").casefold() == "true" else os.getenv("SUPABASE_URL") or None)
    supabase_publishable_key: str | None = Field(default_factory=lambda: None if os.getenv("LOCAL_AUTH", "false").casefold() == "true" else os.getenv("SUPABASE_PUBLISHABLE_KEY") or None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
