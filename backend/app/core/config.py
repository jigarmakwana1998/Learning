import os
from functools import lru_cache

from pydantic import BaseModel
from dotenv import load_dotenv


load_dotenv()


class Settings(BaseModel):
    agent_provider: str = os.getenv("AGENT_PROVIDER", "mock")
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./learning_coach.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "change-this-development-jwt-secret")
    encryption_key: str = os.getenv("APP_ENCRYPTION_KEY", "q0_mL9PZ2Ik1Wl9qVzYmIDQDfL8dbbSbix-AJZAcBLk=")
    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@example.com")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "change-me-now")
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    supabase_publishable_key: str | None = os.getenv("SUPABASE_PUBLISHABLE_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
