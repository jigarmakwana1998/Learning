from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from sqlalchemy import select

from app.adapters.inbound.health import router as health_router
from app.controllers import analytics_router, auth_router, learning_router, sessions_router
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.di.providers import ApplicationProvider
from app.models.database import Base, User


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    # Production Postgres schemas are managed exclusively by Alembic. SQLite is
    # retained for isolated tests and zero-setup local mock development.
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        # Supabase owns production credentials. Its configured admin email gains
        # the application admin role when that authenticated user first calls us.
        if not settings.supabase_url:
            admin = await db.scalar(select(User).where(User.email == settings.admin_email.lower()))
            if admin is None:
                db.add(User(email=settings.admin_email.lower(), password_hash=hash_password(settings.admin_password), role="admin"))
                await db.commit()
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
setup_dishka(make_async_container(ApplicationProvider()), app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(learning_router)
app.include_router(sessions_router)
app.include_router(analytics_router)
