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

1. Build and push backend image to Artifact Registry
2. Apply Terraform with the desired image tag
3. Read `cloud_run_service_url` output
4. Set frontend `VITE_API_URL` to that URL

## Notes

- Cloud Run is intentionally configured for `min_instance_count = 0`
- use the default `run.app` URL first
- do not add a load balancer unless a real requirement appears
