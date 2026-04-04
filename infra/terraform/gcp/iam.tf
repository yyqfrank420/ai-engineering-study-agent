resource "google_project_iam_member" "artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── CI/CD service account permissions ───────────────────────────────────────

# Push container images to Artifact Registry.
resource "google_project_iam_member" "ci_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

# Deploy new revisions to Cloud Run.
resource "google_project_iam_member" "ci_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

# CI also needs to read the internal test credentials that power the
# staging gate. Scope this to the two staging-only secrets instead of
# granting project-wide Secret Manager access.
data "google_secret_manager_secret" "staging_eval" {
  for_each = toset([
    "internal-test-password",
    "internal-test-email-allowlist-raw",
  ])

  project   = var.project_id
  secret_id = each.value
}

resource "google_secret_manager_secret_iam_member" "ci_staging_eval_secret_accessor" {
  for_each = data.google_secret_manager_secret.staging_eval

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ci.email}"
}

# Allow CI to deploy Cloud Run services that run as the backend SA.
# Scoped to the backend SA only — not a project-wide SA user binding.
resource "google_service_account_iam_member" "ci_act_as_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.ci.email}"
}
