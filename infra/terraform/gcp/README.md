# GCP Terraform

Terraform for the cost-first GCP deployment.

Scope:

- enable required APIs
- create Artifact Registry
- create Secret Manager secrets
- create Cloud Run service
- create backend service account and IAM
- optionally create a monthly budget

This module does **not** rely on console provisioning.

If you want Terraform to create secret versions too:

- populate `secret_values`
- set `enabled_secret_names` to the matching env var names

## Expected workflow

1. Apply Terraform when infrastructure or stable runtime config changes
2. Push application changes to `main`
3. GitHub Actions builds the backend image and deploys a no-traffic Cloud Run candidate revision
4. GitHub Actions runs the staging eval suite against the tagged candidate URL
5. GitHub Actions promotes traffic only if the staging gate passes

Terraform owns the long-lived Cloud Run service shape:

- service account
- resource limits
- startup probe
- env vars and Secret Manager bindings
- IAM

CI/CD owns revision rollout:

- image tag selection
- no-traffic candidate deploys
- revision tags
- traffic promotion

## Notes

- Cloud Run is intentionally configured for `min_instance_count = 0`
- use the default `run.app` URL first
- do not add a load balancer unless a real requirement appears
- the initial `container_image` bootstrap override is only for first creation; CI manages images after that
