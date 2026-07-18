resource "google_project_iam_member" "artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_secret_manager_secret_iam_member" "backend_secret_accessor" {
  for_each = local.secret_bindings

  project   = var.project_id
  secret_id = google_secret_manager_secret.app[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "staging_artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.backend_staging.email}"
}

resource "google_secret_manager_secret_iam_member" "staging_secret_accessor" {
  for_each = local.staging_secret_bindings

  project   = var.project_id
  secret_id = google_secret_manager_secret.app[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_staging.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "staging_public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend_staging.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Environment-scoped GitHub Actions permissions ──────────────────────────

# Staging builds candidate images and manages ephemeral/approved tags.
resource "google_project_iam_member" "staging_ci_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_actions_staging.email}"
}

# Cloud Run does not offer service-level deploy IAM, so both identities have
# the project developer role but can act as only their own runtime account.
resource "google_project_iam_member" "staging_ci_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.github_actions_staging.email}"
}

locals {
  staging_ci_secret_ids = toset([
    "internal-test-password",
    "internal-test-email-allowlist-raw",
    "staging-supabase-db-url",
  ])
  production_ci_secret_ids = toset([
    "internal-test-password",
    "internal-test-email-allowlist-raw",
    "production-migration-db-url",
  ])
}

resource "google_secret_manager_secret_iam_member" "ci_staging_eval_secret_accessor" {
  for_each = local.staging_ci_secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.app[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_actions_staging.email}"
}

resource "google_service_account_iam_member" "ci_act_as_staging" {
  service_account_id = google_service_account.backend_staging.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_actions_staging.email}"
}

# Production reads approved images but cannot push or retag them.
resource "google_project_iam_member" "production_ci_artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.github_actions_production.email}"
}

resource "google_project_iam_member" "production_ci_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.github_actions_production.email}"
}

resource "google_secret_manager_secret_iam_member" "ci_production_secret_accessor" {
  for_each = local.production_ci_secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.app[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_actions_production.email}"
}

resource "google_service_account_iam_member" "ci_act_as_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_actions_production.email}"
}

# Transitional rollback only. Apply once with retain_legacy_ci_access=true to
# create the two new identities without breaking existing jobs, update both
# GitHub Environment secrets, then apply the default false state to contract.
resource "google_project_iam_member" "legacy_ci_artifact_registry_writer" {
  count   = var.retain_legacy_ci_access ? 1 : 0
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_project_iam_member" "legacy_ci_run_developer" {
  count   = var.retain_legacy_ci_access ? 1 : 0
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_secret_manager_secret_iam_member" "legacy_ci_secret_accessor" {
  for_each = var.retain_legacy_ci_access ? local.secret_ids : toset([])

  project   = var.project_id
  secret_id = google_secret_manager_secret.app[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_service_account_iam_member" "legacy_ci_act_as_backend" {
  count              = var.retain_legacy_ci_access ? 1 : 0
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_service_account_iam_member" "legacy_ci_act_as_staging" {
  count              = var.retain_legacy_ci_access ? 1 : 0
  service_account_id = google_service_account.backend_staging.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci.email}"
}
