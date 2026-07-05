#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo "SUPABASE_DB_URL is not set." >&2
  exit 1
fi

if ! command -v alembic >/dev/null 2>&1; then
  echo "alembic is required but was not found on PATH. Run: pip install -r backend/requirements.txt" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but was not found on PATH." >&2
  exit 1
fi

alembic -c "$ROOT_DIR/alembic.ini" upgrade head

missing_rls="$(
  psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 <<'SQL'
WITH required_tables(name) AS (
  VALUES
    ('profiles'),
    ('chat_threads'),
    ('chat_messages'),
    ('request_events'),
    ('product_analytics_events'),
    ('search_tool_requests'),
    ('active_streams'),
    ('http_request_logs'),
    ('llm_telemetry'),
    ('analytics_events')
)
SELECT r.name
FROM required_tables AS r
JOIN pg_class AS c ON c.relname = r.name
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND NOT c.relrowsecurity
ORDER BY r.name;
SQL
)"

if [[ -n "$missing_rls" ]]; then
  echo "RLS is disabled for public tables:" >&2
  echo "$missing_rls" >&2
  exit 1
fi
