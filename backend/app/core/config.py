import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


class Settings(BaseModel):
    app_name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Learning Coach API"))
    app_version: str = Field(default_factory=lambda: os.getenv("APP_VERSION", "0.4.0"))
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_harness: str = Field(default_factory=lambda: os.getenv("AGENT_HARNESS", "gemini-cli"))
    litellm_base_url: str = Field(default_factory=lambda: os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    litellm_gemini_base_url: str = Field(default_factory=lambda: os.getenv("LITELLM_GEMINI_BASE_URL") or os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"))
    litellm_api_key: str | None = Field(default_factory=lambda: os.getenv("LITELLM_API_KEY") or None)
    litellm_model: str = Field(default_factory=lambda: os.getenv("LITELLM_MODEL", "agent-model"))
    database_url: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./learning_coach.db"))
    jwt_secret: str = Field(default_factory=lambda: os.getenv("JWT_SECRET", "change-this-development-jwt-secret"))
    encryption_key: str = Field(default_factory=lambda: required_environment("APP_ENCRYPTION_KEY"))
    cors_origins: list[str] = Field(default_factory=lambda: [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8081,http://localhost:19006").split(",") if origin.strip()])
    admin_email: str = Field(default_factory=lambda: os.getenv("ADMIN_EMAIL", "admin@example.com"))
    admin_password: str = Field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "change-me-now"))
    local_auth: bool = Field(default_factory=lambda: os.getenv("LOCAL_AUTH", "false").casefold() == "true")
    supabase_url: str | None = Field(default_factory=lambda: None if os.getenv("LOCAL_AUTH", "false").casefold() == "true" else os.getenv("SUPABASE_URL") or None)
    supabase_publishable_key: str | None = Field(default_factory=lambda: None if os.getenv("LOCAL_AUTH", "false").casefold() == "true" else os.getenv("SUPABASE_PUBLISHABLE_KEY") or None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
