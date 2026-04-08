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

import psycopg
from psycopg.rows import dict_row

from config import settings

POSTGRES_REQUIRED_TABLES = (
    "profiles",
    "chat_threads",
    "chat_messages",
    "request_events",
    "search_tool_requests",
    "http_request_logs",
    "llm_telemetry",
)

POSTGRES_REQUIRED_POLICIES = {
    "profiles": {"profiles_select_own", "profiles_update_own"},
    "chat_threads": {"threads_all_own"},
    "chat_messages": {"messages_all_own"},
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
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                graph_data   TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                role       TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);

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
            """
        )
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN graph_data TEXT")
            conn.commit()
        except Exception:
            pass


@contextmanager
def _connect():
    if settings.use_postgres:
        conn = psycopg.connect(settings.supabase_db_url, row_factory=dict_row)
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
        rows = cursor.fetchall()
        if settings.use_postgres:
            return [dict(row) for row in rows]
        return [dict(row) for row in rows]


def fetchone(query: str, params: tuple[Any, ...] = ()) -> dict | None:
    with _connect() as conn:
        cursor = conn.execute(_adapt_query(query), params)
        row = cursor.fetchone()
        return dict(row) if row else None


def _validate_postgres_schema(conn: psycopg.Connection) -> None:
    public_tables = {
        row["tablename"]
        for row in conn.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            """
        ).fetchall()
    }
    missing_tables = sorted(set(POSTGRES_REQUIRED_TABLES) - public_tables)

    rls_enabled_tables = {
        row["table_name"]
        for row in conn.execute(
            """
            SELECT c.relname AS table_name
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relrowsecurity
            """
        ).fetchall()
    }
    tables_without_rls = sorted(public_tables - rls_enabled_tables)

    policies_by_table: dict[str, set[str]] = {}
    for row in conn.execute(
        """
        SELECT tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
        """
    ).fetchall():
        policies_by_table.setdefault(row["tablename"], set()).add(row["policyname"])

    missing_policies: list[str] = []
    for table_name, required_policies in POSTGRES_REQUIRED_POLICIES.items():
        actual_policies = policies_by_table.get(table_name, set())
        for policy_name in sorted(required_policies - actual_policies):
            missing_policies.append(f"{table_name}.{policy_name}")

    if not missing_tables and not tables_without_rls and not missing_policies:
        return

    problems: list[str] = []
    if missing_tables:
        problems.append(f"missing tables: {', '.join(missing_tables)}")
    if tables_without_rls:
        problems.append(f"RLS disabled: {', '.join(tables_without_rls)}")
    if missing_policies:
        problems.append(f"missing policies: {', '.join(missing_policies)}")

    raise RuntimeError(
        "Postgres schema is not ready for production; "
        + "; ".join(problems)
        + ". Apply docs/supabase/schema.sql before starting the app."
    )
