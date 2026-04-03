locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])

  secret_bindings = {
    ANTHROPIC_API_KEY     = "anthropic-api-key"
    OPENAI_API_KEY        = "openai-api-key"
    SUPABASE_URL          = "supabase-url"
    SUPABASE_ANON_KEY     = "supabase-anon-key"
    SUPABASE_DB_URL       = "supabase-db-url"
    SUPABASE_JWT_ISSUER   = "supabase-jwt-issuer"
    SUPABASE_JWT_SECRET   = "supabase-jwt-secret"
    TURNSTILE_SECRET_KEY  = "turnstile-secret-key"
    FAISS_ARTIFACT_URL    = "faiss-artifact-url"
    FAISS_ARTIFACT_SHA256 = "faiss-artifact-sha256"
  }

  backend_image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}/${var.image_name}:${var.image_tag}"

  base_env_vars = merge(
    {
      FRONTEND_ORIGIN          = var.frontend_origin
      FAISS_ARTIFACT_TIMEOUT_S = tostring(var.faiss_artifact_timeout_s)
    },
    var.env_vars,
  )
}
