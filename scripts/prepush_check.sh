#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/3] Backend tests"
if [ -x "$repo_root/backend/.venv/bin/pytest" ]; then
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-ci-dummy}" \
  OPENAI_API_KEY="${OPENAI_API_KEY:-ci-dummy}" \
  SUPABASE_URL="${SUPABASE_URL:-https://ci-dummy.supabase.co}" \
  SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-ci-dummy}" \
  SUPABASE_DB_URL="${SUPABASE_DB_URL:-}" \
  SUPABASE_JWT_ISSUER="${SUPABASE_JWT_ISSUER:-https://ci-dummy.supabase.co/auth/v1}" \
  SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-ci-dummy-secret-at-least-32-characters-long}" \
  TURNSTILE_SECRET_KEY="${TURNSTILE_SECRET_KEY:-1x0000000000000000000000000000000AA}" \
  FAISS_ARTIFACT_URL="${FAISS_ARTIFACT_URL:-https://ci-dummy.example.com/faiss.tar.gz}" \
  FAISS_ARTIFACT_SHA256="${FAISS_ARTIFACT_SHA256:-0000000000000000000000000000000000000000000000000000000000000000}" \
  FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:5173}" \
  "$repo_root/backend/.venv/bin/pytest" backend/tests --tb=short -q
else
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-ci-dummy}" \
  OPENAI_API_KEY="${OPENAI_API_KEY:-ci-dummy}" \
  SUPABASE_URL="${SUPABASE_URL:-https://ci-dummy.supabase.co}" \
  SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-ci-dummy}" \
  SUPABASE_DB_URL="${SUPABASE_DB_URL:-}" \
  SUPABASE_JWT_ISSUER="${SUPABASE_JWT_ISSUER:-https://ci-dummy.supabase.co/auth/v1}" \
  SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-ci-dummy-secret-at-least-32-characters-long}" \
  TURNSTILE_SECRET_KEY="${TURNSTILE_SECRET_KEY:-1x0000000000000000000000000000000AA}" \
  FAISS_ARTIFACT_URL="${FAISS_ARTIFACT_URL:-https://ci-dummy.example.com/faiss.tar.gz}" \
  FAISS_ARTIFACT_SHA256="${FAISS_ARTIFACT_SHA256:-0000000000000000000000000000000000000000000000000000000000000000}" \
  FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:5173}" \
  python3 -m pytest backend/tests --tb=short -q
fi

echo "[2/3] Frontend type-check and build"
(
  cd "$repo_root/frontend"
  npm ci
  VITE_API_URL="${VITE_API_URL:-https://ci-placeholder.run.app}" npm run build
)

if [ -z "${VERCEL_TOKEN:-}" ] || [ -z "${VERCEL_ORG_ID:-}" ] || [ -z "${VERCEL_PROJECT_ID:-}" ]; then
  echo "[3/3] Skipping Vercel production build preflight"
  echo "Set VERCEL_TOKEN, VERCEL_ORG_ID, and VERCEL_PROJECT_ID to run the Vercel CLI build locally."
  exit 0
fi

echo "[3/3] Vercel production build preflight"
(
  cd "$repo_root/frontend"
  rm -rf .vercel/output
  npx vercel pull --yes --environment=production --token="$VERCEL_TOKEN"
  npx vercel build --prod --token="$VERCEL_TOKEN"
)
