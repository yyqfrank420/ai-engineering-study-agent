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
  [OPENAI_API_KEY]="openai-api-key"
  [SUPABASE_URL]="supabase-url"
  [SUPABASE_ANON_KEY]="supabase-anon-key"
  [SUPABASE_DB_URL]="supabase-db-url"
  [SUPABASE_JWT_ISSUER]="supabase-jwt-issuer"
  [SUPABASE_JWT_SECRET]="supabase-jwt-secret"
  [TURNSTILE_SECRET_KEY]="turnstile-secret-key"
  [FAISS_ARTIFACT_URL]="faiss-artifact-url"
  [FAISS_ARTIFACT_SHA256]="faiss-artifact-sha256"
  [GOOGLE_OAUTH_CLIENT_ID]="google-oauth-client-id"
  [GOOGLE_OAUTH_CLIENT_SECRET]="google-oauth-client-secret"
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

# Parse .env: skip comments and blank lines, strip inline comments
parse_env_value() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | head -1 | sed "s/^${key}=//" | sed 's/#.*//' | xargs
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
  echo -n "$value" | gcloud secrets versions add "$secret_id" \
    --project="$PROJECT_ID" \
    --data-file=- \
    --quiet

  ((pushed++)) || true
done

echo ""
echo "Done. Pushed: $pushed, Skipped: $skipped"
