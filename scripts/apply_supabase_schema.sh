#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_FILE="$ROOT_DIR/docs/supabase/schema.sql"

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo "SUPABASE_DB_URL is not set." >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but was not found on PATH." >&2
  exit 1
fi

psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"

missing_rls="$(
  psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT c.relname
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'r'
  AND NOT c.relrowsecurity
ORDER BY c.relname;
SQL
)"

if [[ -n "$missing_rls" ]]; then
  echo "RLS is disabled for public tables:" >&2
  echo "$missing_rls" >&2
  exit 1
fi
