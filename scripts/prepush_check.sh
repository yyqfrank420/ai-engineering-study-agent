#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/3] Backend tests"
if [ -x "$repo_root/backend/.venv/bin/python" ]; then
  python_cmd=("$repo_root/backend/.venv/bin/python" -m pytest)
else
  python_cmd=(python3 -m pytest)
fi

log_dir="$(mktemp -d)"
trap 'rm -rf "$log_dir"' EXIT

run_backend_group() {
  local group="$1"
  shift
  local log_file="$log_dir/backend-${group}.log"
  (
    ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-test-disabled}" \
    OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
    SUPABASE_URL="${SUPABASE_URL:-https://ci-dummy.supabase.co}" \
    SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-ci-dummy}" \
    SUPABASE_DB_URL="${SUPABASE_DB_URL:-}" \
    SUPABASE_JWT_ISSUER="${SUPABASE_JWT_ISSUER:-https://ci-dummy.supabase.co/auth/v1}" \
    SUPABASE_JWT_SECRET="${SUPABASE_JWT_SECRET:-ci-dummy-secret-at-least-32-characters-long}" \
    TURNSTILE_SECRET_KEY="${TURNSTILE_SECRET_KEY:-1x0000000000000000000000000000000AA}" \
    FAISS_ARTIFACT_URL="${FAISS_ARTIFACT_URL:-https://ci-dummy.example.com/faiss.tar.gz}" \
    FAISS_ARTIFACT_SHA256="${FAISS_ARTIFACT_SHA256:-0000000000000000000000000000000000000000000000000000000000000000}" \
    FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:5173}" \
    "${python_cmd[@]}" "$@" --tb=short -q
  ) >"$log_file" 2>&1
}

pids=()
groups=()

run_backend_group api-integration \
  backend/tests/test_api_security.py \
  backend/tests/test_internal_auth_and_telemetry.py \
  backend/tests/test_internal_dashboard_routes.py \
  backend/tests/test_observability_and_dashboard.py \
  backend/tests/test_system_workflows.py \
  backend/tests/test_thread_routes_integration.py &
pids+=("$!")
groups+=(api-integration)

run_backend_group agent-rag-llm \
  backend/tests/test_agent_tools.py \
  backend/tests/test_graph_grounding_prompts.py \
  backend/tests/test_llm_adapter.py \
  backend/tests/test_mode_controls.py \
  backend/tests/test_node_selected_service.py \
  backend/tests/test_orchestrator_node.py \
  backend/tests/test_pipeline_steps.py \
  backend/tests/test_rag_retrieval.py \
  backend/tests/test_rag_worker.py \
  backend/tests/test_search_tool_flow.py &
pids+=("$!")
groups+=(agent-rag-llm)

run_backend_group storage-security \
  backend/tests/test_database_adapter_postgres.py \
  backend/tests/test_faiss_artifact.py \
  backend/tests/test_faiss_artifact_security.py \
  backend/tests/test_observability_core.py \
  backend/tests/test_postgres_schema_guardrails.py \
  backend/tests/test_resource_limits.py \
  backend/tests/test_storage_integrity.py \
  backend/tests/test_supabase_auth_adapter.py &
pids+=("$!")
groups+=(storage-security)

run_backend_group eval-graph-artifacts \
  backend/tests/test_canonical_graph.py \
  backend/tests/test_eval_metrics.py \
  backend/tests/test_graph_artifacts_schema.py \
  backend/tests/test_staging_runner.py &
pids+=("$!")
groups+=(eval-graph-artifacts)

backend_status=0
for index in "${!pids[@]}"; do
  group="${groups[$index]}"
  if wait "${pids[$index]}"; then
    echo "  [ok] $group"
  else
    backend_status=1
    echo "  [fail] $group"
    cat "$log_dir/backend-${group}.log"
  fi
done

if [ "$backend_status" -ne 0 ]; then
  exit "$backend_status"
fi

echo "[2/3] Frontend checks"
(
  cd "$repo_root/frontend"
  npm ci --prefer-offline --no-audit --no-fund

  frontend_log_dir="$(mktemp -d)"
  trap 'rm -rf "$frontend_log_dir"' EXIT

  run_frontend_check() {
    local name="$1"
    shift
    "$@" >"$frontend_log_dir/${name}.log" 2>&1
  }

  frontend_pids=()
  frontend_checks=()

  run_frontend_check lint npm run lint &
  frontend_pids+=("$!")
  frontend_checks+=(lint)

  run_frontend_check test npm run test &
  frontend_pids+=("$!")
  frontend_checks+=(test)

  run_frontend_check build env VITE_API_URL="${VITE_API_URL:-https://ci-placeholder.run.app}" npm run build &
  frontend_pids+=("$!")
  frontend_checks+=(build)

  frontend_status=0
  for index in "${!frontend_pids[@]}"; do
    check="${frontend_checks[$index]}"
    if wait "${frontend_pids[$index]}"; then
      echo "  [ok] $check"
    else
      frontend_status=1
      echo "  [fail] $check"
      cat "$frontend_log_dir/${check}.log"
    fi
  done

  exit "$frontend_status"
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
