# GCP Terraform

Terraform for the cost-first GCP deployment.

Scope:

- enable required APIs
- create Artifact Registry
- create Secret Manager secrets
- create separate production and staging Cloud Run services
- create separate production and staging service accounts and IAM
- optionally create a monthly budget

This module creates secret containers but deliberately does not accept secret
values: Terraform stores every managed value in state. After the first apply,
populate versions directly in Secret Manager:

```bash
GCP_PROJECT_ID='<project-id>' bash scripts/populate_secrets.sh
```

When adding a required secret to an existing service, create its container before
Terraform updates the Cloud Run binding. For the Kimi graph builder:

```bash
terraform -chdir=infra/terraform/gcp apply \
  -target='google_secret_manager_secret.app["moonshot-api-key"]'
GCP_PROJECT_ID='<project-id>' bash scripts/populate_secrets.sh
terraform -chdir=infra/terraform/gcp apply
```

The middle step reads `MOONSHOT_API_KEY` from the ignored `backend/.env` file and
creates the first `moonshot-api-key` version. Do not deploy the Kimi-enabled image
until the final apply mounts that version in both Cloud Run services.

## Expected workflow

1. Apply Terraform when infrastructure or stable runtime config changes
2. Provision the `agent_staging` database role and fixed reset function once with `scripts/provision_staging_role.py --apply`
3. Protect the `staging-eval` and `production` GitHub Environments
4. A trusted PR builds one image, resets only the `staging` schema, and evaluates a tagged no-traffic revision
5. Main locates the exact tree-approved digest, migrates `public`, runs a no-traffic production smoke, and then promotes traffic

Terraform owns the long-lived Cloud Run service shape:

- service account
- resource limits
- startup probe
- env vars and Secret Manager bindings
- IAM

The staging service is fixed at zero minimum and one maximum instance, runs as
`agent-backend-staging`, uses `DB_SCHEMA=staging`, and receives only the
`staging-supabase-db-url` database secret. The production service receives
`DB_SCHEMA=public`. The separate `production-migration-db-url` secret is readable
only by the main deployment job and is never mounted into either service.

GitHub federation is split too. Set `GCP_SERVICE_ACCOUNT` in the protected
`staging-eval` Environment to the `staging_ci_service_account_email` output and
set the same-named secret in `production` to `production_ci_service_account_email`.
Their OIDC bindings require the exact Environment-bearing subject: staging can
push candidates and read only staging credentials; production can read approved
images and the main-only migration identity but cannot push or retag images. The
legacy `ci_service_account_email` is deliberately unprivileged for one
expand-then-contract cycle and can be removed after both paths are proven.

Cut over without an outage in two reviewed applies:

1. apply with `-var=retain_legacy_ci_access=true`, which expands access by adding
   both scoped identities while temporarily retaining the old identity;
2. set the Environment secrets to the new outputs and prove staging plus
   production impersonation from their protected workflows;
3. apply again with the default `retain_legacy_ci_access=false`, verify the old
   identity has no WIF/IAM bindings, and retain the account itself as the rollback
   marker until the recovery window closes.

Never leave the transition switch enabled while accepting unreviewed staging
workflow changes: it deliberately restores the former broad identity.

Set `internal_dashboard_allowlist_raw` in the environment-specific tfvars file
to a comma-separated list of the email addresses allowed to open the internal
dashboard.

CI/CD owns revision rollout:

- immutable digest and tree-approval tag selection
- no-traffic candidate deploys
- revision tags
- traffic promotion

## Notes

- Cloud Run is intentionally configured for `min_instance_count = 0`
- use the default `run.app` URL first
- do not add a load balancer unless a real requirement appears
- the initial `container_image` bootstrap override is only for first creation; CI manages images after that
- Terraform creates secret containers only. Populate `STAGING_SUPABASE_DB_URL` and
  `PRODUCTION_MIGRATION_DB_URL` through `scripts/populate_secrets.sh` after their
  roles have been reviewed and provisioned.
