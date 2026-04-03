# Cloud Run Cost-First Deployment

Last updated: 2026-04-03

## Goal

Deploy the backend on **Google Cloud Run** with:

- `min instances = 0`
- request-based billing
- no external load balancer
- stable public `run.app` URL
- Terraform-managed provisioning only

This is the lowest-cost serious hosting target for the current backend shape.

## Why Cloud Run

- True scale-to-zero when idle
- No always-on instance charge
- No AWS load balancer requirement
- Native HTTPS endpoint out of the box
- Good fit for occasional personal use, with cold starts accepted as the cost tradeoff

## Important Tradeoff

The backend loads FAISS artifacts during startup. With `min instances = 0`, the first request after idle will be slower.

That is intentional in this deployment mode.

The frontend should not pretend the backend is warm. It should use an explicit `Prepare` flow before the first send in a cold session.

## Target Architecture

- `Vercel`
  - frontend only
- `Cloud Run`
  - backend API
  - public HTTPS `run.app` URL
  - `min instances = 0`
- `Artifact Registry`
  - backend container image
- `Secret Manager`
  - runtime secrets for backend service
- `Supabase`
  - auth and persistent app data
- external FAISS bundle host
  - pointed to by `FAISS_ARTIFACT_URL`

No GCP load balancer is required for the first production version.

## Terraform Requirement

Provisioning must be code-only.

No manual Cloud Run service creation.
No manual service account setup.
No manual secret injection in the console.

Terraform should provision:

- enabled GCP APIs
- Artifact Registry repository
- backend service account
- IAM bindings required for Cloud Run and Secret Manager
- Secret Manager secrets and secret versions where appropriate
- Cloud Run service
- Cloud Run public invoker policy if the backend is intentionally public
- optional budget alerts

If we later add a custom domain, that should also be Terraform-managed.

## Recommended Terraform Layout

Suggested directory:

`infra/terraform/gcp/`

Suggested files:

- `providers.tf`
- `versions.tf`
- `variables.tf`
- `locals.tf`
- `artifact_registry.tf`
- `service_account.tf`
- `secrets.tf`
- `cloud_run.tf`
- `iam.tf`
- `outputs.tf`
- `budgets.tf`

If we later manage Vercel, Cloudflare, or Supabase through IaC too, keep those as separate provider-specific modules instead of mixing everything into one file.

## Cloud Run Service Settings

Recommended initial settings:

- CPU: small baseline, sized after measuring cold start
- memory: enough to load FAISS and Python dependencies comfortably
- `min_instance_count = 0`
- `max_instance_count` capped conservatively
- request timeout long enough for SSE and agent startup
- concurrency kept modest for predictable latency
- ingress public
- request-based billing

The exact CPU / memory shape should be set after one measurement pass, not guessed forever.

## Secrets

Backend secrets should come from Secret Manager, not plain Terraform variables in state if avoidable.

At minimum:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_DB_URL`
- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWT_SECRET`
- `TURNSTILE_SECRET_KEY`
- `FAISS_ARTIFACT_URL`
- `FAISS_ARTIFACT_SHA256`

Some of these can be plain env vars in low-risk setups, but the intended end state is secret-backed runtime config.

## Networking

Cloud Run works without a load balancer for this project.

Use:

- the default public `run.app` URL for the backend
- `VITE_API_URL` in the frontend pointing to that URL

This avoids the fixed cost of an external GCP HTTP load balancer.

## Readiness Model

The frontend should not assume the backend is warm.

Instead:

- on app load, readiness is `unknown`
- the user clicks `Prepare`
- frontend calls a lightweight readiness endpoint
- that request wakes Cloud Run if needed
- UI waits until backend reports ready
- then send is enabled

This is the cost-first UX contract.

## Deployment Flow

1. Build backend image
2. Push image to Artifact Registry
3. Apply Terraform
4. Terraform updates Cloud Run service to new image
5. Frontend receives backend URL from Terraform output or env sync

No manual service edits in console.

## Non-Goals For First Pass

- no GCP load balancer
- no custom domain requirement
- no min instance warm pool
- no multi-region failover
- no complex private networking

## Follow-Up Work

After first deploy, measure:

- cold start time
- FAISS load time
- `/prepare` median and p95 latency
- first chat send latency after prepare

If cold starts are too painful, only then reconsider `min instances = 1`.

## Current Repo Status

Already in repo:

- backend Dockerfile
- Terraform scaffold under `infra/terraform/gcp/`
- `/api/prepare` readiness endpoint
- frontend `Prepare` flow

Still operational work:

- fill real secret values
- build and push the backend image
- apply Terraform against the real GCP project
- wire Vercel env vars to the Cloud Run URL

## How To Use The Free Credits

Do not treat the credits as permission to ignore cost shape.

Use them to measure the tradeoff properly:

1. Start with `min instances = 0`
2. Measure cold-start readiness and first-send latency for a few days
3. If the UX is unacceptable, temporarily switch to `min instances = 1`
4. Compare:
   - cold-start latency
   - monthly burn rate
   - whether the difference is actually worth paying for later

Recommended credit strategy:

- keep the default production target as `min instances = 0`
- use the credits to run short benchmark windows with `min instances = 1`
- keep a Terraform-managed budget alert enabled so spending never drifts silently

The credits should buy information, not permanent waste.
