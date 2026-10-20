from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from app.adapters.inbound.health import router as health_router
from app.controllers import analytics_router, auth_router, learning_router, observability_router, sessions_router
from app.core.config import get_settings
from app.core.database import engine
from app.di.providers import ApplicationProvider
from app.models.database import Base


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    # Production Postgres schemas are managed exclusively by Alembic. SQLite is
    # retained for isolated tests and zero-setup local development.
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
setup_dishka(make_async_container(ApplicationProvider()), app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(learning_router)
app.include_router(sessions_router)
app.include_router(analytics_router)
app.include_router(observability_router)
