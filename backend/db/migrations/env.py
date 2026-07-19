from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
ALLOWED_SCHEMAS = {"public", "staging"}


def _database_schema() -> str:
    schema = os.environ.get("DB_SCHEMA", "public").strip().lower()
    if schema not in ALLOWED_SCHEMAS:
        raise RuntimeError("DB_SCHEMA must be either 'public' or 'staging'")
    return schema


def _database_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "SUPABASE_DB_URL or DATABASE_URL is required to run Alembic migrations"
        )
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def run_migrations_offline() -> None:
    schema = _database_schema()
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=schema,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    schema = _database_schema()
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        search_path = f'"{schema}", auth' if schema == "public" else f'"{schema}"'
        connection.exec_driver_sql(f"SET search_path TO {search_path}")
        # SQLAlchemy autobegins on SET. End that implicit transaction before
        # Alembic takes ownership so migrations can use autocommit blocks for
        # concurrent indexes without losing the session-level search path.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema,
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
