output "backend_image" {
  value       = local.backend_image
  description = "Fully qualified Artifact Registry image path for the backend."
}

output "cloud_run_service_url" {
  value       = google_cloud_run_v2_service.backend.uri
  description = "Public Cloud Run URL for the backend."
}

output "staging_cloud_run_service_url" {
  value       = google_cloud_run_v2_service.backend_staging.uri
  description = "Public Cloud Run URL for the isolated staging service."
}

output "backend_service_account_email" {
  value       = google_service_account.backend.email
  description = "Service account used by the backend."
}

output "staging_service_account_email" {
  value       = google_service_account.backend_staging.email
  description = "Service account used by the staging backend."
}

output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.backend.id
  description = "Artifact Registry repository resource ID."
}

output "ci_service_account_email" {
  value       = google_service_account.ci.email
  description = "Deprecated unprivileged GitHub Actions service account retained for transition rollback."
}

output "staging_ci_service_account_email" {
  value       = google_service_account.github_actions_staging.email
  description = "Set as GCP_SERVICE_ACCOUNT only in the protected staging-eval GitHub Environment."
}

output "production_ci_service_account_email" {
  value       = google_service_account.github_actions_production.email
  description = "Set as GCP_SERVICE_ACCOUNT only in the protected production GitHub Environment."
}

output "wif_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Full WIF provider resource name. Use as GCP_WORKLOAD_IDENTITY_PROVIDER secret in GitHub."
}
