import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from app.adapters.inbound.health import router as health_router
from app.controllers import auth_router, learning_router, observability_router
from app.core.config import get_settings
from app.core.database import engine
from app.di.providers import ApplicationProvider
from app.models.database import AgentRun, Base
from sqlalchemy import update

# Route every library's logs (SQLAlchemy, httpx, LiteLLM, agents) to stdout so
# `docker compose logs` shows them. LOG_LEVEL=DEBUG prints everything.
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("uvicorn").setLevel(_log_level)

@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    # Production Postgres schemas are managed exclusively by Alembic. SQLite is
    # retained for isolated tests and zero-setup local development.
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    # Runs execute in-process, so any still "running" at startup were lost in a
    # restart. ponytail: single API process; a job queue needs a smarter check.
    async with engine.begin() as connection:
        await connection.execute(
            update(AgentRun)
            .where(AgentRun.status == "running")
            .values(status="failed", result={"error": "Interrupted by a server restart; please try again."})
        )
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
setup_dishka(make_async_container(ApplicationProvider()), app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(learning_router)
app.include_router(observability_router)
