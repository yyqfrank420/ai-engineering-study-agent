# Canonical Quality and Release System

## One local and GitHub entry point

`ci/quality.json` owns offline groups, commands, tracked-test assignment,
change-impact rules, live suites, and PR budgets. `scripts/ci` is the only runner:

```bash
./scripts/ci offline
./scripts/ci offline --group api-integration
./scripts/ci browser --suite pr --target http://localhost:5173
./scripts/ci live --suite pr --target https://candidate.example \
  --input artifacts/live-eval/browser-results.json
```

`scripts/prepush_check.sh` only delegates to `./scripts/ci offline`. The manifest
validation test discovers every `backend/tests/test_*.py` file and fails when a
test is omitted or a stale path remains. Frontend and ingestion commands use
glob-covering test runners, so newly tracked tests are automatically included.

The stable branch checks are `CI required` and `Live eval required`. Both workflows
listen to `pull_request`, trusted pushes, and `merge_group`. While the seed corpus
is pending human review, the live check succeeds with an explicit bootstrap result
before installing browsers, authenticating to GCP, building images, mutating
staging, or calling a model. Production rollout is likewise disabled until corpus
approval. Run
`scripts/configure_main_branch_protection.sh owner/repo` to inspect the current and
proposed branch protection without writing. Add `--apply` only after reviewing the
payload.

## Trust and staging isolation

The live workflow uses `pull_request`, never `pull_request_target`. Documentation
and isolated CSS/assets receive a successful no-live-calls result. Unknown paths
are fail-safe AI-impacting. An AI-impacting fork receives no secrets and fails with
instructions for a maintainer to copy the reviewed patch to a same-repository
branch.

Same-repository AI changes wait for approval of the `staging-eval` GitHub
Environment. Its federated GCP identity is bound to that exact
Environment-bearing OIDC subject, can read only staging secrets, and cannot
impersonate the separate production deployer. The `production` Environment has an
independently bound identity. Staging mutation is globally serialized. A database
advisory lock is held while the constant `staging` schema is dropped, recreated,
and migrated from scratch. `DB_SCHEMA` accepts only `public` or `staging`;
application connections and Alembic both pin their search path. Before and after
reset, probes must show that the staging login cannot select from or update
`public.profiles`. The staging login has no database-wide schema-creation privilege;
it can invoke only a fixed, security-definer reset function that recreates the
constant `staging` schema. While the lock is still held, reset derives a stable UUID
from the allowlisted internal-test email and inserts that identity into
`staging.profiles`. The browser then authenticates through the app's protected
internal-login flow. The staging role has no access to managed Supabase Auth or
production application tables. Production retains its `auth.users` foreign key and
`auth.uid()` policies; staging uses the equivalent request-JWT subject expression in
its policies because Supabase intentionally restricts the managed `auth` schema.

One-time database setup is an explicit write:

```bash
SUPABASE_ADMIN_DB_URL='...' STAGING_DB_PASSWORD='...' \
  python scripts/provision_staging_role.py --apply
```

Review the script and recovery plan first. It creates/rotates only
`agent_staging`, revokes its explicit public privileges, grants object creation only
inside `staging`, and exposes the fixed reset function. Store its URL as
`staging-supabase-db-url`. Store a separate, main-only migration identity as
`production-migration-db-url`.

## Browser evidence and budgets

The PR suite contains eight journeys: grounded RAG, memory, graph-off, research,
node follow-up, graph expansion, an applied domain, and prompt injection. Empty and
oversized input stay in deterministic API tests and spend no model calls.

Playwright uses the real frontend and production WebSocket protocol. It records
received events, final answers, graph JSON, rendered-node counts, screenshots,
persistence, cleanup, latency, fallback, dashboard readiness, and per-thread model
telemetry. For the allowlisted internal identity on the isolated `staging` schema
only, the retrieval workers also emit bounded book passages, external search
snippets, and provenance so citations can be verified; production users never
receive these evidence events. Its
trace is rewritten before upload so bearer credentials and the internal password
are redacted. JSON, JUnit, HTML, screenshots, and traces are retained for 30 days
and are not committed as answer truth.

To diagnose a small set without replaying the whole corpus, manually dispatch
`Scheduled evaluation` with suite `diagnostic` and one to eight space-separated
case IDs. The same targeted mode is available locally by repeating `--case`, for
example `./scripts/ci browser --suite diagnostic --case citations ...`. Diagnostic
runs use the PR-sized time, application-call, and judge-call budgets and cannot
approve or replace the full corpus review.

PR limits are eight cases, 50 application calls, 16 judge calls, and 15 minutes.
The report includes provider, model, input/output tokens, latency, fallback, and an
estimated cost under a dated price table. Provider rate limits, transport failures,
and timeouts are reported as infrastructure failures; they never silently pass or
masquerade as a quality regression.

## Corpus approval and semantic policy

`backend/eval/corpus/v1/cases.json` is a 20-case, versioned seed corpus. It contains
conversation steps, UI modes, categories, risk tags, deterministic expectations,
rubric references with pass/borderline/fail anchors, criticality, provenance, and
per-case approval metadata. Generated answers remain artifacts; only prompts,
rubrics, invariants, and intentionally reviewed exemplars belong in source control.

The corpus currently says `pending_human_review`. This is deliberate. To activate
the blocking semantic judge:

1. Merge the pending-corpus quality system while branch protection still requires
   only `CI required`, create and protect the `staging-eval` Environment, then
   manually dispatch `Scheduled evaluation` with suite `full` on `main`. While the
   corpus is pending, this trusted main-only path builds the exact checked-out tree
   under a temporary `corpus-bootstrap-*` tag, deploys it to staging with no traffic,
   and removes the temporary tag after the run. Once the corpus is approved, the
   workflow fails closed unless the main tree already has an approved digest and
   never uses the bootstrap build path.
2. Download the 30-day evaluation artifact, then open `review.html` and
   `semantic-review.html`.
3. Review or correct every proposed dimension label and exemplar.
4. Calibrate the judge to at least 85% agreement with no more than one critical
   false pass, then record the release, agreement, false-pass count, and UTC time
   in `approval.calibration`.
5. Mark all 20 cases approved, record reviewer and UTC time, then record the
   canonical corpus SHA-256 produced by `eval.quality_corpus.corpus_sha256()`.
6. Run the focused corpus and semantic-gate tests, merge the approval change, and
   only then require `Live eval required` in branch protection.

Record each case's artifact run ID and `reviewed_grades`, then compute the
calibration rather than entering it by inspection:

```bash
PYTHONPATH=backend python -m eval.calibration \
  --input artifacts/live-eval/live-results.json
```

Copy the passing report's release, agreement, critical-false-pass count, and UTC
time into `approval.calibration` before calculating the approval hash.

Until those steps are complete, `--require-approved-corpus` fails closed. Once
approved, deterministic failures block immediately. A clear semantic failure gets
one independent second judgment; two clear failures block. A borderline grade or
judge disagreement requires manual review. No critical dimension may fail, and at
least 85% of non-critical dimensions must pass.

An override is an audited `workflow_dispatch` requiring original run ID, full
commit SHA, authenticated reviewer, and reason. Dispatch it from the tested
commit's own branch/ref; the workflow requires `GITHUB_SHA` to equal the supplied
commit so GitHub attaches the required check to the right revision. The protected
workflow downloads the original deployment identity, verifies the exact
commit/tree/digest, records a 30-day audit artifact, and only then publishes the
exact-tree approval tag.

## Exact-digest production promotion

Successful staging evaluation tags the immutable image digest with the Git tree
hash. The production workflow starts only after a successful main `Live eval
required` run and will not rebuild a missing approval. It then:

1. applies the reviewed migrations to `public` with the main-only identity;
2. deploys the approved digest as a no-traffic production candidate;
3. exercises readiness, internal authentication, dashboard, persistence, graph
   rendering, cleanup, and one real-model browser journey;
4. sends 100% traffic to that tagged candidate only after success.

The previous Cloud Run revision is left available for rollback. Nightly runs rotate
four cases, while Sunday runs cover the full corpus. Staging revision and ephemeral
image tags are removed after evaluation; the content-addressed approval tag and
30-day evidence remain.
