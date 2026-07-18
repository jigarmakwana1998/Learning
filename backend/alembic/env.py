from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models.database import Base

config = context.config
target_metadata = Base.metadata


def migration_database_url() -> str:
    """Use Alembic's synchronous drivers for the app's async DB URL."""
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1).replace("sqlite+aiosqlite://", "sqlite://", 1)


config.set_main_option("sqlalchemy.url", migration_database_url())


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()


if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
