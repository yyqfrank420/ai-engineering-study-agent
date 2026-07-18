#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo "SUPABASE_DB_URL is not set." >&2
  exit 1
fi

DB_SCHEMA="${DB_SCHEMA:-public}"
if [[ "$DB_SCHEMA" != "public" && "$DB_SCHEMA" != "staging" ]]; then
  echo "DB_SCHEMA must be either 'public' or 'staging'." >&2
  exit 1
fi

if ! command -v alembic >/dev/null 2>&1; then
  echo "alembic is required but was not found on PATH. Run: pip install -r backend/requirements-dev.txt" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but was not found on PATH." >&2
  exit 1
fi

alembic -c "$ROOT_DIR/alembic.ini" upgrade head

missing_rls="$(
  psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 -v app_schema="$DB_SCHEMA" <<'SQL'
WITH required_tables(name) AS (
  VALUES
    ('alembic_version'),
    ('profiles'),
    ('chat_threads'),
    ('chat_messages'),
    ('request_events'),
    ('product_analytics_events'),
    ('search_tool_requests'),
    ('active_streams'),
    ('http_request_logs'),
    ('llm_telemetry'),
    ('analytics_events'),
    ('rate_limit_events')
)
SELECT r.name
FROM required_tables AS r
JOIN pg_class AS c ON c.relname = r.name
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = :'app_schema'
  AND c.relkind = 'r'
  AND NOT c.relrowsecurity
ORDER BY r.name;
SQL
)"

if [[ -n "$missing_rls" ]]; then
  echo "RLS is disabled for $DB_SCHEMA tables:" >&2
  echo "$missing_rls" >&2
  exit 1
fi

missing_indexes="$(
  psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 -v app_schema="$DB_SCHEMA" <<'SQL'
WITH required_indexes(name) AS (
  VALUES
    ('uq_chat_messages_client_turn_role'),
    ('idx_rate_limit_key_type_expiry'),
    ('idx_rate_limit_expiry')
)
SELECT r.name
FROM required_indexes AS r
WHERE to_regclass(format('%I.%I', :'app_schema', r.name)) IS NULL
ORDER BY r.name;
SQL
)"

if [[ -n "$missing_indexes" ]]; then
  echo "Required $DB_SCHEMA indexes are missing:" >&2
  echo "$missing_indexes" >&2
  exit 1
fi
