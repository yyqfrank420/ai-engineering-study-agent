resource "google_service_account" "backend" {
  account_id   = replace(var.service_name, "_", "-")
  display_name = "AI Study Agent Backend"
}

resource "google_service_account" "backend_staging" {
  account_id   = replace(var.staging_service_name, "_", "-")
  display_name = "AI Study Agent Staging Eval"
}

# Legacy identity retained without WIF or project permissions during the
# expand-then-contract transition. Remove it after both environment-scoped
# identities have completed a successful staging and production run.
resource "google_service_account" "ci" {
  account_id   = "github-actions-ci"
  display_name = "GitHub Actions CI/CD (deprecated)"
}

resource "google_service_account" "github_actions_staging" {
  account_id   = "github-actions-staging"
  display_name = "GitHub Actions Staging Evaluation"
}

resource "google_service_account" "github_actions_production" {
  account_id   = "github-actions-production"
  display_name = "GitHub Actions Production Deployment"
}
