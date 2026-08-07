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
Backend changes also run the full configured source set under Coverage.py with a
90% line floor. Frontend coverage includes every production TypeScript and TSX
module, including modules that no test imports, and enforces 90% statements,
lines, and functions plus 75% branches. These suites use dummy credentials and
fake provider clients; live model evaluation remains a separate protected gate.

The stable branch checks are `CI required` and `Live eval required`. Both workflows
listen to `pull_request`, trusted pushes, and `merge_group`. The 20-case corpus is
approved and content-addressed, so trusted AI-impacting changes run the protected
live gate and production promotion requires that exact approved tree. A future
pending corpus still takes the fail-safe bootstrap path before installing browsers,
authenticating to GCP, building images, mutating staging, or calling a model. Run
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

Playwright uses the real frontend and production WebSocket protocol. The eight PR
cases run with total concurrency four and a separate two-case graph lane, so two
independent graph-producing journeys can run together. Every case
attempt receives its own authenticated browser context and thread. Turns within a
multi-turn case remain sequential on that context, and result ordering remains the
canonical corpus ordering even when cases finish out of order.

The Anthropic semaphore allows four streams per application process/Cloud Run
instance; it is not a global account cap. It bounds Opus architecture and Sonnet QA
calls. Kimi graph construction uses the Moonshot OpenAI-compatible endpoint and the
two-case graph lane remains the suite-level concurrency bound.

Each attempt records received events, final answers, graph JSON, rendered-node
counts, screenshots, redacted traces, persistence, cleanup, fallback, and typed
blocking failures classified as `quality` or `infrastructure`. A case receives
exactly one additional attempt only when every blocking failure from the first
attempt is infrastructure-related. Quality and mixed failures are never retried.
Both attempts remain in the capture with their thread IDs, timings, screenshots,
traces, failures, and cleanup evidence; a successful retry does not erase the first
attempt or its model usage.

For the allowlisted internal identity on the isolated `staging` schema only, the
retrieval workers also emit bounded book passages, external search snippets, and
provenance so citations can be verified; production users never receive these
evidence events. Traces are rewritten before upload so bearer credentials and the
internal password are redacted. JSON, JUnit, HTML, screenshots, and traces are
retained for 30 days and are not committed as answer truth.

To diagnose a small set without replaying the whole corpus, manually dispatch
`Scheduled evaluation` with suite `diagnostic` and one to eight space-separated
case IDs. The same targeted mode is available locally by repeating `--case`, for
example `./scripts/ci browser --suite diagnostic --case citations ...`. Diagnostic
runs use the PR-sized time, application-call, and judge-call budgets and cannot
approve or replace the full corpus review. When the approved corpus has no
`approved-tree-<tree>` image for the workflow-dispatch ref, this diagnostic path
builds and deploys an ephemeral image for that exact checked-out tree, then removes
its temporary tag. It never publishes an approval tag. Scheduled, nightly, and full
runs still require an existing exact-tree approval when the corpus is approved.

`Semantic review replay` has two isolated modes. The default `full-scheduled` mode
preserves the existing behavior: it authenticates a successful full scheduled run,
reuses its deterministic browser capture, and records semantic proposals without
generating application answers again. `pr-selective` is a trusted, main-dispatched
manual review lane for rejudging an ordered subset of the eight PR cases from one
exact failed same-repository `Live eval required` run. It requires the exact run ID,
artifact name, source head SHA, authenticated reviewer, and a specific reason.

The selective lane verifies the completed failed PR run and immutable GitHub
artifact, binds the recorded deployment to the two distinct source-head/base merge
parents, tree, and image digest, and then uses `eval.evidence_replay subset` to write
a diagnostic capture containing only the selected results, case states, and
attributed telemetry. It runs `scripts/ci live --suite diagnostic --capture-replay`
with the selected cases, so it performs judge calls only: it does not open a browser,
call the application model, authenticate to GCP, deploy, or mutate staging. Every
selected semantic decision must be `pass`; failure, manual review, infrastructure
failure, reordered/duplicate results, or missing provenance fails closed. The
30-day replay artifact contains the subset capture, live result, and provenance with
original/derived hashes, source run/head/tested commit/tree/digest, selection,
artifact digest, replay commit/actor, reviewer, and reason. Selective replay is
review evidence only and does not itself publish an image approval or deploy.

PR evaluation limits are eight cases, 50 application provider attempts, and 16
judge provider attempts. The timeout chain is deliberately nested: the backend
agent stops at 360 seconds, the Playwright turn waits at most 390 seconds so it can
capture the typed terminal event, and Cloud Run accepts a request for at most 420
seconds. The browser-suite timeout scales with the number of turns and the two-wide
graph lane, with a 60-minute hard ceiling. Semantic judging is capped at 20 minutes
for PR/smoke/diagnostic suites and 60 minutes for full suites. The outer GitHub jobs
allow 90 minutes for the PR gate and 130 minutes for scheduled evaluation, including
installation, deployment, judging, artifact upload, and cleanup; the former 15/30
minute limits no longer apply.

Each turn records total, first-event, and first-token latency plus client and server
request IDs. Those IDs join browser evidence to per-operation model telemetry,
including provider/model, generation duration, provider semaphore queue wait,
fallback, and every provider attempt. Reports publish deterministic nearest-rank
p50/p95 summaries for case end-to-end, turn end-to-end, first event, and first token;
final infrastructure-failed cases are excluded from those baselines. Latency remains
report-only with no manifest thresholds while five clean runs are collected.
Reviewed baselines can then add blocking thresholds without changing the 360-second
correctness deadline. Stage durations may overlap and are reported independently
rather than added into a false critical path.

Application cost accounting is likewise retry-aware: all threads from all browser
attempts are attributed back to their case, then split by model operation and
provider attempt. Input/output tokens, prompt-cache reads, queue wait, and estimated USD use a dated
price table; fallback and failed charged attempts are included. Protected evaluation revisions enable
Anthropic's five-minute prompt cache for repeated stable role prompts. Production app revisions leave
it disabled because sparse traffic may not recover the cache-write premium. Kimi automatic-cache hits
use their discounted input price. Judge usage is
reported separately and per case. An unknown model price is an infrastructure
failure, never zero cost. Cost limits are currently report-only and unset while at
least five clean runs establish per-case and suite baselines; only reviewed limits
should be promoted to blocking. Provider rate limits, transport failures, and
timeouts remain infrastructure failures and never masquerade as quality regressions.

## Corpus approval and semantic policy

`backend/eval/corpus/v1/cases.json` is a 20-case, versioned approved corpus. It contains
conversation steps, UI modes, categories, risk tags, deterministic expectations,
rubric references with pass/borderline/fail anchors, criticality, provenance, and
per-case approval metadata. Generated answers remain artifacts; only prompts,
rubrics, invariants, and intentionally reviewed exemplars belong in source control.

The current `2026-07-19.v2` corpus and every case say `approved`; the manifest stores
its reviewer, review runs, reviewed grades, canonical SHA-256, and a calibrated
`semantic-rubric-judge-v5` result of 90.3614% agreement with zero critical false
passes. Calibration run `31014653521` approved the Anthropic judge model
`claude-sonnet-5` against frozen browser evidence from reviewed main run `29689189704`, commit
`fc3dbf97910b59005c2e25d825852f47d5d790c7`, browser-evidence SHA-256
`f6075c9091a4594848cf34dc82c535308467585c75a73bc333578e654518700f`.

`corpus_sha256()` hashes behavior only: corpus-level and per-case approval metadata
are excluded while prompts, rubrics, UI modes, and deterministic expectations remain
covered. Recording calibration provenance therefore cannot change the corpus
identity or create a digest/storage-prefix cycle. A separate approval-manifest hash
covers all approval labels, reviewers, calibration baselines, and evidence identity
except its own digest field. `--require-approved-corpus` validates that full
manifest, so either behavior or provenance tampering fails closed. A future corpus
revision must return changed cases to human review, run the full protected capture,
record every case's artifact run and reviewed grades, recalibrate, and publish a new
approved hash before it can block or promote.

Compute calibration from saved evidence rather than entering it by inspection:

```bash
PYTHONPATH=backend python -m eval.calibration \
  --input artifacts/live-eval/live-results.json \
  --evidence artifacts/live-eval/browser-results.json \
  --context artifacts/live-eval/replay-context.json
```

With the approved corpus, deterministic failures block immediately. A clear
semantic failure gets one independent second judgment; two clear failures block. A
borderline grade or judge disagreement requires manual review. PR and scheduled
monitoring use the explicit `report-only` policy for an approved corpus: the report,
JUnit skip, HTML evidence, and GitHub warning remain visible, but review is not
mislabeled as broken CI. Deterministic, confirmed semantic, and infrastructure
failures still exit non-zero under either policy. No
critical dimension may fail, and at least 85% of non-critical dimensions must pass.

## Immutable judge-calibration evidence

Judge calibration replays the exact browser evidence that humans reviewed; it never
generates fresh application answers. The manual `Promote calibration evidence`
workflow reads the pinned identity from the approved corpus rather than accepting a
different run at dispatch. It authenticates that exact successful `main`
`Scheduled evaluation`, source commit and run context, source corpus behavior,
ordered passing 20-case browser capture, and browser digest. It then stores both the
content-addressed browser JSON and its promotion manifest under
`reviewed/<corpus-sha>/` in the private GCS evaluation-evidence bucket. Uniform
bucket access, public-access prevention, versioning, a one-year retention policy,
and a two-year lifecycle protect the evidence from casual replacement or deletion.

The weekly `Judge calibration` workflow resolves the reviewed evidence digest,
source run, and source commit from the corpus calibration identity, downloads and
rehashes that exact GCS object, and runs `--capture-replay`. Only judge calls are
charged. Before replay it requires both GCS objects, rehashes the browser capture,
and verifies that the promotion manifest matches the pinned corpus digest, evidence
digest, source run, source commit, and judge model. Missing objects or identity
mismatches fail visibly; there is no pending/no-op success path. After authenticating
the untouched legacy capture, it writes a replay copy with the current behavior-only
corpus digest; the approved evidence hash still covers the untouched original. It
then compares the active judge prompt/model with the fixed human grades and fails below 85%
agreement, above one critical false pass, on an identity mismatch, or after an
agreement drop greater than five percentage points from the approved calibration.
Reports are kept in 90-day GitHub artifacts and copied to GCS calibration history.

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
