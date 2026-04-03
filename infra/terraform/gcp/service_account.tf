resource "google_service_account" "backend" {
  account_id   = replace(var.service_name, "_", "-")
  display_name = "AI Study Agent Backend"
}

# Service account used by GitHub Actions CI/CD to push images and deploy.
# Scoped to minimum required roles — see iam.tf for bindings.
resource "google_service_account" "ci" {
  account_id   = "github-actions-ci"
  display_name = "GitHub Actions CI/CD"
}
