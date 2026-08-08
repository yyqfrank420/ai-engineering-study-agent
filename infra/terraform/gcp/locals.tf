locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    # Required for Workload Identity Federation token exchange
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])

  secret_bindings = {
    ANTHROPIC_API_KEY                 = "anthropic-api-key"
    MOONSHOT_API_KEY                  = "moonshot-api-key"
    OPENAI_API_KEY                    = "openai-api-key"
    POSTHOG_API_KEY                   = "posthog-api-key"
    SUPABASE_URL                      = "supabase-url"
    SUPABASE_ANON_KEY                 = "supabase-anon-key"
    SUPABASE_DB_URL                   = "supabase-db-url"
    SUPABASE_JWT_ISSUER               = "supabase-jwt-issuer"
    SUPABASE_JWT_SECRET               = "supabase-jwt-secret"
    TURNSTILE_SECRET_KEY              = "turnstile-secret-key"
    FAISS_ARTIFACT_URL                = "faiss-artifact-url"
    FAISS_ARTIFACT_SHA256             = "faiss-artifact-sha256"
    INTERNAL_TEST_PASSWORD            = "internal-test-password"
    INTERNAL_TEST_EMAIL_ALLOWLIST_RAW = "internal-test-email-allowlist-raw"
  }

  staging_secret_bindings = merge(local.secret_bindings, {
    SUPABASE_DB_URL = "staging-supabase-db-url"
  })

  secret_ids = toset(concat(
    values(local.secret_bindings),
    values(local.staging_secret_bindings),
    ["production-migration-db-url"],
  ))

  backend_image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}/${var.image_name}:${var.image_tag}"

  base_env_vars = merge(
    {
      FRONTEND_ORIGIN                  = var.frontend_origin
      DB_SCHEMA                        = "public"
      FAISS_ARTIFACT_TIMEOUT_S         = tostring(var.faiss_artifact_timeout_s)
      ANTHROPIC_MAX_CONCURRENT_STREAMS = "4"
      ANTHROPIC_PROMPT_CACHE_ENABLED   = "false"
      INTERNAL_DASHBOARD_ALLOWLIST_RAW = var.internal_dashboard_allowlist_raw
      OTEL_ENVIRONMENT                 = "production"
      POSTHOG_HOST                     = "https://eu.i.posthog.com"
    },
    var.env_vars,
  )

  staging_env_vars = merge(
    local.base_env_vars,
    {
      DB_SCHEMA        = "staging"
      OTEL_ENVIRONMENT = "staging"
    },
  )
}
