"""Opt-in migration checks against an explicitly configured disposable local database."""

import importlib
import os
import uuid
from urllib.parse import urlparse

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


@pytest.mark.parametrize("legacy_turns", [0, 2])
def test_message_sequence_migration_installs_database_owned_order(legacy_turns):
    database_url = os.environ.get("MESSAGE_SEQUENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set MESSAGE_SEQUENCE_TEST_DATABASE_URL to a disposable local PostgreSQL database"
        )
    if urlparse(database_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail(
            "Message sequence migration tests require a local disposable database"
        )
    engine = create_engine(
        database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    schema = "message_order_test_" + uuid.uuid4().hex
    migration = importlib.import_module(
        "db.migrations.versions.20260912_0007_message_sequence"
    )
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                conn.exec_driver_sql(
                    """
                    CREATE TABLE chat_messages (
                        id uuid PRIMARY KEY,
                        thread_id uuid NOT NULL,
                        user_id uuid NOT NULL,
                        role text NOT NULL CHECK (role IN ('user', 'assistant')),
                        content text NOT NULL,
                        client_request_id text,
                        created_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                thread_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
                insert = text(
                    "INSERT INTO chat_messages(id,thread_id,user_id,role,content,client_request_id) "
                    "VALUES(:id,:thread,:user,:role,:content,:request)"
                )
                for turn in range(legacy_turns):
                    for role in ("user", "assistant"):
                        conn.execute(
                            insert,
                            {
                                "id": str(uuid.uuid4()),
                                "thread": thread_id,
                                "user": user_id,
                                "role": role,
                                "content": f"{role}-{turn}",
                                "request": f"turn-{turn}",
                            },
                        )
                before = conn.exec_driver_sql(
                    "SELECT id,role,content,created_at,client_request_id FROM chat_messages ORDER BY id"
                ).all()
                with Operations.context(MigrationContext.configure(conn)):
                    migration.upgrade()
                assert (
                    conn.exec_driver_sql(
                        "SELECT id,role,content,created_at,client_request_id FROM chat_messages ORDER BY id"
                    ).all()
                    == before
                )
                properties = conn.execute(
                    text(
                        "SELECT is_identity,identity_generation,is_nullable FROM information_schema.columns "
                        "WHERE table_schema=:schema AND table_name='chat_messages' AND column_name='message_sequence'"
                    ),
                    {"schema": schema},
                ).one()
                assert tuple(properties) == ("YES", "ALWAYS", "NO")
                sequence = conn.execute(
                    text(
                        "SELECT cache_size,cycle FROM pg_sequences WHERE schemaname=:schema"
                    ),
                    {"schema": schema},
                ).one()
                assert tuple(sequence) == (1, False)
                assert conn.exec_driver_sql(
                    "SELECT role FROM chat_messages ORDER BY message_sequence"
                ).scalars().all() == [
                    role for _ in range(legacy_turns) for role in ("user", "assistant")
                ]
                conn.execute(
                    insert,
                    {
                        "id": str(uuid.uuid4()),
                        "thread": thread_id,
                        "user": user_id,
                        "role": "user",
                        "content": "old writer",
                        "request": None,
                    },
                )
                assert (
                    conn.exec_driver_sql(
                        "SELECT message_sequence FROM chat_messages WHERE content='old writer'"
                    ).scalar_one()
                    == legacy_turns * 2 + 1
                )
                indexes = set(
                    conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE schemaname=:schema AND tablename='chat_messages'"
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                assert {
                    "uq_chat_messages_sequence",
                    "idx_chat_messages_thread_sequence",
                } <= indexes
            finally:
                # Schema creation and the migration are both rolled back after every test.
                transaction.rollback()
    finally:
        engine.dispose()
