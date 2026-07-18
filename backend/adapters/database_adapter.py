# ─────────────────────────────────────────────────────────────────────────────
# File: backend/adapters/database_adapter.py
# Purpose: Thin wrapper around the app database.
#          Uses Supabase Postgres when SUPABASE_DB_URL is configured, otherwise
#          falls back to local SQLite for tests and local development.
# Language: Python
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3
from contextlib import contextmanager
from typing import Any

from config import settings


class _PsycopgProxy:
    def connect(self, *args, **kwargs):
        import psycopg as real_psycopg
        from psycopg.rows import dict_row

        kwargs.setdefault("row_factory", dict_row)
        return real_psycopg.connect(*args, **kwargs)


psycopg = _PsycopgProxy()

POSTGRES_REQUIRED_TABLES = (
    "alembic_version",
    "profiles",
    "chat_threads",
    "chat_messages",
    "request_events",
    "product_analytics_events",
    "search_tool_requests",
    "active_streams",
    "http_request_logs",
    "llm_telemetry",
    "analytics_events",
    "rate_limit_events",
)

POSTGRES_REQUIRED_POLICIES = {
    "profiles": {"profiles_select_own", "profiles_update_own"},
    "chat_threads": {"threads_all_own"},
    "chat_messages": {"messages_all_own"},
    "active_streams": {"active_streams_all_own"},
}

POSTGRES_REQUIRED_COLUMNS = {
    "chat_messages": {"client_request_id"},
    "rate_limit_events": {
        "key_hash",
        "event_type",
        "created_at_epoch",
        "expires_at_epoch",
    },
}

POSTGRES_REQUIRED_INDEXES = {
    "uq_chat_messages_client_turn_role",
    "idx_rate_limit_key_type_expiry",
    "idx_rate_limit_expiry",
}


def init_db() -> None:
    if settings.use_postgres:
        with _connect() as conn:
            _validate_postgres_schema(conn)
        return

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_threads (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(id),
                title TEXT NOT NULL DEFAULT 'New chat',
                graph_data TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES chat_threads(id),
                user_id TEXT NOT NULL REFERENCES profiles(id),
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                client_request_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_chat_threads_user_last_seen
                ON chat_threads(user_id, last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_created
                ON chat_messages(thread_id, created_at);

            CREATE TABLE IF NOT EXISTS request_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(id),
                event_type TEXT NOT NULL,
                created_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_request_events_user_type_created
                ON request_events(user_id, event_type, created_at_epoch);

            CREATE TABLE IF NOT EXISTS product_analytics_events (
                id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES profiles(id),
                anonymous_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                properties_json TEXT,
                created_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_product_analytics_events_created
                ON product_analytics_events(created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_product_analytics_events_type_created
                ON product_analytics_events(event_type, created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_product_analytics_events_actor_created
                ON product_analytics_events(anonymous_id, created_at_epoch);

            CREATE TABLE IF NOT EXISTS search_tool_requests (
                request_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(id),
                thread_id TEXT NOT NULL REFERENCES chat_threads(id),
                requested INTEGER NOT NULL DEFAULT 0,
                created_at_epoch REAL NOT NULL,
                expires_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_search_tool_requests_user_thread
                ON search_tool_requests(user_id, thread_id);

            CREATE TABLE IF NOT EXISTS active_streams (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES profiles(id),
                stream_type TEXT NOT NULL,
                created_at_epoch REAL NOT NULL,
                expires_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_active_streams_user_type
                ON active_streams(user_id, stream_type, expires_at_epoch);

            CREATE TABLE IF NOT EXISTS http_request_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                metadata_json TEXT,
                created_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_http_request_logs_created
                ON http_request_logs(created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_http_request_logs_user_created
                ON http_request_logs(user_id, created_at_epoch);

            CREATE TABLE IF NOT EXISTS llm_telemetry (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                thread_id TEXT,
                operation TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                output_chars INTEGER NOT NULL,
                used_fallback INTEGER NOT NULL DEFAULT 0,
                error_type TEXT,
                metadata_json TEXT,
                created_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_llm_telemetry_created
                ON llm_telemetry(created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_llm_telemetry_user_created
                ON llm_telemetry(user_id, created_at_epoch);

            CREATE TABLE IF NOT EXISTS analytics_events (
                id TEXT PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_category TEXT NOT NULL,
                user_id TEXT,
                anonymous_id TEXT,
                session_id TEXT,
                thread_id TEXT,
                request_id TEXT,
                trace_id TEXT,
                client_request_id TEXT,
                schema_version INTEGER NOT NULL DEFAULT 1,
                app_version TEXT NOT NULL DEFAULT '0.1.0',
                environment TEXT NOT NULL DEFAULT 'development',
                numeric_value REAL,
                unit TEXT,
                properties_json TEXT,
                created_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_analytics_events_created
                ON analytics_events(created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_analytics_events_category_created
                ON analytics_events(event_category, created_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_analytics_events_request
                ON analytics_events(request_id);
            CREATE INDEX IF NOT EXISTS idx_analytics_events_trace
                ON analytics_events(trace_id);

            CREATE TABLE IF NOT EXISTS rate_limit_events (
                id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at_epoch REAL NOT NULL,
                expires_at_epoch REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rate_limit_key_type_expiry
                ON rate_limit_events(key_hash, event_type, expires_at_epoch);
            CREATE INDEX IF NOT EXISTS idx_rate_limit_expiry
                ON rate_limit_events(expires_at_epoch);
            """
        )
        message_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()
        }
        if "client_request_id" not in message_columns:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN client_request_id TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client_turn_role
            ON chat_messages(user_id, thread_id, client_request_id, role)
            WHERE client_request_id IS NOT NULL
            """
        )


@contextmanager
def _connect():
    if settings.use_postgres:
        conn = psycopg.connect(
            settings.supabase_db_url,
            options=f"-c search_path={settings.db_schema},auth",
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _adapt_query(query: str) -> str:
    if settings.use_postgres:
        return query.replace("?", "%s")
    return query


def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    with _connect() as conn:
        conn.execute(_adapt_query(query), params)


def fetchall(query: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with _connect() as conn:
        cursor = conn.execute(_adapt_query(query), params)
        return [dict(row) for row in cursor.fetchall()]


def fetchone(query: str, params: tuple[Any, ...] = ()) -> dict | None:
    with _connect() as conn:
        cursor = conn.execute(_adapt_query(query), params)
        row = cursor.fetchone()
        return dict(row) if row else None


def _validate_postgres_schema(conn) -> None:
    schema = settings.db_schema
    schema_tables = {
        row["tablename"]
        for row in conn.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = %s
            """,
            (schema,),
        ).fetchall()
    }
    missing_tables = sorted(set(POSTGRES_REQUIRED_TABLES) - schema_tables)

    columns_by_table: dict[str, set[str]] = {}
    for row in conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
        """,
        (schema,),
    ).fetchall():
        columns_by_table.setdefault(row["table_name"], set()).add(row["column_name"])
    missing_columns = sorted(
        f"{table_name}.{column_name}"
        for table_name, required_columns in POSTGRES_REQUIRED_COLUMNS.items()
        for column_name in required_columns - columns_by_table.get(table_name, set())
    )

    schema_indexes = {
        row["indexname"]
        for row in conn.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = %s
            """,
            (schema,),
        ).fetchall()
    }
    missing_indexes = sorted(POSTGRES_REQUIRED_INDEXES - schema_indexes)

    rls_enabled_tables = {
        row["table_name"]
        for row in conn.execute(
            """
            SELECT c.relname AS table_name
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relkind = 'r'
              AND c.relrowsecurity
            """,
            (schema,),
        ).fetchall()
    }
    tables_without_rls = sorted(set(POSTGRES_REQUIRED_TABLES) - rls_enabled_tables)

    policies_by_table: dict[str, set[str]] = {}
    for row in conn.execute(
        """
        SELECT tablename, policyname
        FROM pg_policies
        WHERE schemaname = %s
        """,
        (schema,),
    ).fetchall():
        policies_by_table.setdefault(row["tablename"], set()).add(row["policyname"])

    missing_policies: list[str] = []
    for table_name, required_policies in POSTGRES_REQUIRED_POLICIES.items():
        actual_policies = policies_by_table.get(table_name, set())
        for policy_name in sorted(required_policies - actual_policies):
            missing_policies.append(f"{table_name}.{policy_name}")

    if (
        not missing_tables
        and not missing_columns
        and not missing_indexes
        and not tables_without_rls
        and not missing_policies
    ):
        return

    problems: list[str] = []
    if missing_tables:
        problems.append(f"missing tables: {', '.join(missing_tables)}")
    if missing_columns:
        problems.append(f"missing columns: {', '.join(missing_columns)}")
    if missing_indexes:
        problems.append(f"missing indexes: {', '.join(missing_indexes)}")
    if tables_without_rls:
        problems.append(f"RLS disabled: {', '.join(tables_without_rls)}")
    if missing_policies:
        problems.append(f"missing policies: {', '.join(missing_policies)}")

    raise RuntimeError(
        f"Postgres schema '{schema}' is not ready; "
        + "; ".join(problems)
        + ". Run Alembic migrations before starting the app: bash scripts/apply_supabase_schema.sh."
    )
