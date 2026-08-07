#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# File: scripts/populate_secrets.sh
# Purpose: Reads backend/.env and pushes each value as a new version to GCP
#          Secret Manager. Safe to re-run — adds a new version each time.
# Language: bash
# Connects to: GCP Secret Manager
# Inputs:  backend/.env (local secrets file, gitignored)
#          GCP_PROJECT_ID env var
#          ENV_FILE env var (optional override)
# Outputs: Secret versions created in GCP Secret Manager
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-}"
ENV_FILE="${ENV_FILE:-$(dirname "$0")/../backend/.env}"

# Map: env var name → Secret Manager secret ID
declare -A SECRET_MAP
SECRET_MAP=(
  [ANTHROPIC_API_KEY]="anthropic-api-key"
  [MOONSHOT_API_KEY]="moonshot-api-key"
  [OPENAI_API_KEY]="openai-api-key"
  [SUPABASE_URL]="supabase-url"
  [SUPABASE_ANON_KEY]="supabase-anon-key"
  [SUPABASE_DB_URL]="supabase-db-url"
  [STAGING_SUPABASE_DB_URL]="staging-supabase-db-url"
  [PRODUCTION_MIGRATION_DB_URL]="production-migration-db-url"
  [SUPABASE_JWT_ISSUER]="supabase-jwt-issuer"
  [SUPABASE_JWT_SECRET]="supabase-jwt-secret"
  [TURNSTILE_SECRET_KEY]="turnstile-secret-key"
  [FAISS_ARTIFACT_URL]="faiss-artifact-url"
  [FAISS_ARTIFACT_SHA256]="faiss-artifact-sha256"
  [INTERNAL_TEST_PASSWORD]="internal-test-password"
  [INTERNAL_TEST_EMAIL_ALLOWLIST_RAW]="internal-test-email-allowlist-raw"
)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: GCP_PROJECT_ID is not set" >&2
  exit 1
fi

echo "Reading $ENV_FILE ..."

# Parse a dotenv assignment without sourcing executable shell code. Values may
# legitimately contain '#', spaces, or '=' and must reach Secret Manager intact.
parse_env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import ast
import sys

path, key = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.rstrip("\r\n")
        if not line.startswith(f"{key}="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            try:
                value = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                pass
        print(value, end="")
        break
PY
}

pushed=0
skipped=0

for env_key in "${!SECRET_MAP[@]}"; do
  secret_id="${SECRET_MAP[$env_key]}"
  value=$(parse_env_value "$env_key")

  if [[ -z "$value" ]]; then
    echo "  SKIP  $env_key — not found or empty in .env"
    ((skipped++)) || true
    continue
  fi

  echo "  PUSH  $env_key → $secret_id"
  printf '%s' "$value" | gcloud secrets versions add "$secret_id" \
    --project="$PROJECT_ID" \
    --data-file=- \
    --quiet

  ((pushed++)) || true
done

echo ""
echo "Done. Pushed: $pushed, Skipped: $skipped"
