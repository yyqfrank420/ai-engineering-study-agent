# Preserve existing Secret Manager resources while changing their Terraform
# instance keys from environment variable names to immutable secret IDs.
moved {
  from = google_secret_manager_secret.app["ANTHROPIC_API_KEY"]
  to   = google_secret_manager_secret.app["anthropic-api-key"]
}

moved {
  from = google_secret_manager_secret.app["FAISS_ARTIFACT_SHA256"]
  to   = google_secret_manager_secret.app["faiss-artifact-sha256"]
}

moved {
  from = google_secret_manager_secret.app["FAISS_ARTIFACT_URL"]
  to   = google_secret_manager_secret.app["faiss-artifact-url"]
}

moved {
  from = google_secret_manager_secret.app["INTERNAL_TEST_EMAIL_ALLOWLIST_RAW"]
  to   = google_secret_manager_secret.app["internal-test-email-allowlist-raw"]
}

moved {
  from = google_secret_manager_secret.app["INTERNAL_TEST_PASSWORD"]
  to   = google_secret_manager_secret.app["internal-test-password"]
}

moved {
  from = google_secret_manager_secret.app["OPENAI_API_KEY"]
  to   = google_secret_manager_secret.app["openai-api-key"]
}

moved {
  from = google_secret_manager_secret.app["SUPABASE_ANON_KEY"]
  to   = google_secret_manager_secret.app["supabase-anon-key"]
}

moved {
  from = google_secret_manager_secret.app["SUPABASE_DB_URL"]
  to   = google_secret_manager_secret.app["supabase-db-url"]
}

moved {
  from = google_secret_manager_secret.app["SUPABASE_JWT_ISSUER"]
  to   = google_secret_manager_secret.app["supabase-jwt-issuer"]
}

moved {
  from = google_secret_manager_secret.app["SUPABASE_JWT_SECRET"]
  to   = google_secret_manager_secret.app["supabase-jwt-secret"]
}

moved {
  from = google_secret_manager_secret.app["SUPABASE_URL"]
  to   = google_secret_manager_secret.app["supabase-url"]
}

moved {
  from = google_secret_manager_secret.app["TURNSTILE_SECRET_KEY"]
  to   = google_secret_manager_secret.app["turnstile-secret-key"]
}

# Expand-then-contract the legacy CI identity without briefly removing its
# access while the environment-scoped identities are being proven.
moved {
  from = google_project_iam_member.ci_artifact_registry_writer
  to   = google_project_iam_member.legacy_ci_artifact_registry_writer[0]
}

moved {
  from = google_project_iam_member.ci_run_developer
  to   = google_project_iam_member.legacy_ci_run_developer[0]
}

moved {
  from = google_secret_manager_secret_iam_member.ci_staging_eval_secret_accessor["internal-test-email-allowlist-raw"]
  to   = google_secret_manager_secret_iam_member.legacy_ci_secret_accessor["internal-test-email-allowlist-raw"]
}

moved {
  from = google_secret_manager_secret_iam_member.ci_staging_eval_secret_accessor["internal-test-password"]
  to   = google_secret_manager_secret_iam_member.legacy_ci_secret_accessor["internal-test-password"]
}

moved {
  from = google_service_account_iam_member.ci_act_as_backend
  to   = google_service_account_iam_member.legacy_ci_act_as_backend[0]
}

moved {
  from = google_service_account_iam_member.ci_wif_binding
  to   = google_service_account_iam_member.legacy_ci_wif_binding[0]
}
