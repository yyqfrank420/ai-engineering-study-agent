# ─────────────────────────────────────────────────────────────────────────────
# File: infra/terraform/gcp/workload_identity.tf
# Purpose: Workload Identity Federation for GitHub Actions — keyless GCP auth.
#          Allows GitHub Actions to impersonate the CI service account without
#          storing long-lived JSON keys in GitHub Secrets.
# Language: HCL (Terraform)
# Connects to: github.com (OIDC token issuer), google_service_account.ci
# Inputs:  github_repo variable
# Outputs: wif_provider_name (via outputs.tf)
# ─────────────────────────────────────────────────────────────────────────────

variable "github_repo" {
  description = "GitHub repo in owner/repo format. Scopes WIF to this repo only."
  type        = string
  default     = "yyqfrank420/ai-engineering-study-agent"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "WIF pool for GitHub Actions CI/CD"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  oidc {
    # GitHub's OIDC issuer — tokens are issued at workflow runtime, not stored anywhere.
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # Map GitHub OIDC claims to Google IAM attributes.
  # `attribute.repository` is used below to scope access to one specific repo.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  # Hard-scope: only OIDC tokens from this exact repo can use this provider.
  # Prevents other repos (including forks) from impersonating the CI SA.
  attribute_condition = "assertion.repository == '${var.github_repo}'"
}

# Allow GitHub Actions from this repo to impersonate the CI service account.
# `principalSet` matches any token from the repo (any branch, any workflow).
resource "google_service_account_iam_member" "ci_wif_binding" {
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
