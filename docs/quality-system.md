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
listen to `pull_request`, trusted pushes, and `merge_group`. AI-impacting changes run
the automated browser and semantic checks. Human corpus labels and judge calibration
are optional evaluation tools; pending review metadata does not block execution or
promotion. A successful live check records the tested Git tree and immutable image
digest. Production still requires that exact image and successful smoke checks.
Run `scripts/configure_main_branch_protection.sh owner/repo` to inspect the current
and proposed branch protection without writing. Add `--apply` only after reviewing
the payload.

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
independently bound identity. Production accepts only successful push or manual
workflow runs from this repository's `main` branch, checked before source checkout.
Staging mutation is globally serialized. A database
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

Browser corpus `2026-09-25.v1` selects the visible on/off diagram modes and answers
the optional diagram-choice dialog. Completion requires the composer to leave its
generating state and a captured WebSocket `done` event; the follow-up Send button
can remain visible during generation. Diagram paths expose their underlying
directed connection members so the browser can verify every connection, including
duplicates and replies, when the canvas bundles several records into one path.

Staging request concurrency is 16, owned by
`ci/quality.json` at `live.budgets.staging_request_concurrency`. Terraform and both
evaluation deployments read that budget. Runtime validation requires at least
twice the browser case concurrency to leave HTTP capacity alongside long-lived
WebSockets. A September 11 full-corpus run exhausted the previous four-request
limit with four browser cases and received Cloud Run 429 responses because its
single instance had no request capacity. Staging retains a maximum of one instance
and serialized evaluation workflows. Each deployment verifies Cloud Run's returned
request concurrency against the budget before browser evaluation and records the
verified value in `deployment.json`. Production retains its separate concurrency
setting.

The Anthropic semaphore allows four streams per application process/Cloud Run
instance; it is not a global account cap. It bounds Opus architecture and Sonnet QA
calls. Kimi graph construction uses the Moonshot OpenAI-compatible endpoint and the
two-case graph lane remains the suite-level concurrency bound.

Each attempt records received events, final answers, graph JSON, rendered-node
counts, screenshots, redacted traces, persistence, cleanup, fallback, and typed
blocking failures classified as `quality` or `infrastructure`. Paid browser cases
do not retry automatically. A whole-case retry repeats every model call made before
an infrastructure fault, so a new protected run requires an explicit operator action.

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
runs use the PR-sized time, application-call, and judge-call budgets. A manually
dispatched full or diagnostic run can build an ephemeral image when that exact tree
has no previously passed image. Its temporary tag is removed after evaluation.
Scheduled and nightly runs require an existing `approved-tree-<tree>` image to avoid
implicit candidate builds. Only the successful protected PR evaluation publishes that
tag; scheduled captures do not grant deployment approval.

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
selected semantic decision must be `pass` or `manual_review` with a passing blocking
status. Failure, infrastructure errors, reordered/duplicate results, or missing
provenance fail closed. The
30-day replay artifact contains the subset capture, live result, and provenance with
original/derived hashes, source run/head/tested commit/tree/digest, selection,
artifact digest, replay commit/actor, reviewer, and reason. Selective replay is
review evidence only and does not itself publish an image approval or deploy.

PR evaluation limits are eight cases, 64 application provider attempts, and 16
judge provider attempts. The current PR corpus has 62 logical application calls on
its complete one-repair paths. Provider retry and fallback paths have a theoretical
144-attempt first-pass ceiling. The tagged staging revision atomically reserves one
shared quota record before each provider request and rejects attempt 65 before it is
sent. This leaves two attempts for transient provider failures while placing a hard
cost boundary below the failure envelope. Production traffic does not set this
evaluation-only quota. The timeout chain is deliberately nested: the backend
agent envelope is 940 seconds, with model work stopping at 910 seconds to retain persistence
headroom. The Playwright turn waits at most 970 seconds so it can capture the typed terminal event,
and Cloud Run accepts a request for at most 1000
seconds. The browser-suite timeout scales with the number of turns and the two-wide
graph lane, with a 60-minute hard ceiling. Semantic judging is capped at 20 minutes
for PR/smoke/diagnostic suites and 60 minutes for full suites. Each semantic judge
request has a 120-second deadline and at most one transport retry. This request
deadline shares the suite's existing wall-clock and provider-attempt budgets;
it does not extend either limit. Exhausted retries record a safe exception class
and HTTP status when available, without provider messages or request data.
The outer GitHub jobs
allow 90 minutes for the PR gate and 150 minutes for scheduled evaluation, including
installation, deployment, judging, artifact upload, and cleanup; the former 15/30
minute limits no longer apply.

Scheduled nightly and full suites use the same pre-request quota with a 150-attempt
cap. Diagnostic dispatches use the 64-attempt PR cap.
Every scheduled browser failure or blocking semantic outcome fails the workflow.
Borderline semantic findings are retained as nonblocking review information. Scheduled artifacts retain evidence for 90 days. `deployment.json`
binds the run to its commit, Git tree, immutable image digest, tagged Cloud Run revision,
pipeline mode, and suite. The browser results record the cases that ran.

Protected internal staged evaluations capture each valid semantic gate result together
with its candidate records and review inputs. These captures require an evaluation run
ID and an allowlisted non-production caller. They are absent from ordinary responses
and analytics. This retains the first rejection when a correction later fails.

Each turn records total, first-event, and first-token latency plus client and server
request IDs. Those IDs join browser evidence to per-operation model telemetry,
including provider/model, generation duration, provider semaphore queue wait,
fallback, and every provider attempt. Reports publish deterministic nearest-rank
p50/p95 summaries for case end-to-end, turn end-to-end, first event, and first token;
final infrastructure-failed cases are excluded from those baselines. Latency remains
report-only with no manifest thresholds while five clean runs are collected.
Reviewed baselines can then add blocking thresholds without changing the 940-second
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
should be promoted to blocking. Explicitly incomplete provider usage, including a
timeout before an acceptance event, leaves total cost unknown and reports a known
subtotal. This accounting uncertainty is nonblocking in report-only mode and blocks
when cost policy is blocking. Malformed or missing telemetry remains an infrastructure
failure. Unrecovered provider rate limits, transport failures, and
timeouts remain infrastructure failures and never masquerade as quality regressions.

## Automated semantic policy and optional calibration

`backend/eval/corpus/v1/cases.json` is a versioned 20-case corpus containing prompts,
UI modes, deterministic expectations, and anchored rubrics. The PR suite selects
eight cases. Generated answers remain evidence artifacts.

Deterministic and critical semantic failures block immediately. A clear noncritical
failure gets one independent second judgment; two clear failures block. More than
15% failing noncritical dimensions is a clear failure. A borderline dimension cannot
hide that failure. Borderline-only results and judge disagreements remain
`manual_review` in reports and use the default `report-only` exit policy. Infrastructure
errors, missing accounting, and configured blocking cost limits still fail.
`--manual-review-policy blocking` explicitly restores a blocking review policy.

The corpus may retain `pending_human_review` metadata while automated checks run.
That status records the absence of human labels; it is not a release prerequisite.
`semantic-rubric-judge-v10`, Anthropic, and `claude-sonnet-5` are the versioned judge
selection. The Anthropic request uses high reasoning effort with an 8192-token
budget shared by reasoning and structured output. The judge receives the case
and rubrics before artifact sources, with numbered evidence chunks in source
order. Reports record the active provider, model, and prompt release.
Calibration remains pending.

`corpus_sha256()` hashes prompts, rubrics, UI modes, and deterministic expectations.
It excludes human approval metadata, so adding labels cannot change behavior identity.
The optional `--require-approved-corpus` mode verifies the full human approval manifest
and calibrated judge identity. Optional calibration requires a complete 20-case
capture, reviewed grades, reviewer identity, and immutable evidence provenance.
Manually dispatch `Scheduled evaluation` with suite `full` to collect that capture.
It does not publish a deployment approval tag.

For the first calibration, keep aggregate corpus approval pending while recording
all 20 human-reviewed cases and the pinned judge and browser evidence identity.
Every case's `review_run_id` must match the pinned `evidence_run_id`. Compute the
baseline from a full semantic replay of that capture with `--capture-replay`;
the original application-run report is not a semantic replay. The frozen
judge-selection JSON contains `format_version: 1`, `provider`, and `model`.

```bash
PYTHONPATH=backend python -m eval.calibration \
  --input artifacts/live-eval/live-results.json \
  --evidence artifacts/live-eval/browser-results.json \
  --context artifacts/live-eval/replay-context.json \
  --judge-selection artifacts/live-eval/judge-selection.json
```

After calibration passes, record its computed results and complete aggregate
corpus approval and the approved manifest hash. Calibration does not approve the
corpus or change its review records.


## Immutable judge-calibration evidence

Judge calibration replays the exact browser evidence that humans reviewed; it never
generates fresh application answers. The manual `Promote calibration evidence`
workflow reads the pinned identity from the approved corpus. It authenticates the
exact completed same-repository `Scheduled evaluation`, source commit and run
context, source corpus behavior, ordered complete 20-case browser capture, dashboard
success, and browser digest. The source may be a candidate branch and may conclude
`failure`. Complete captured product failures are eligible negative examples; missing turns,
terminal events, answers, artifact references, or infrastructure-failed cases are ineligible.
Calibration retains deterministic failures even when its semantic judge passes a response.
Every human-reviewed case must identify that same evidence run. It then stores both the
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

The judge receives the public graph's directed flow, synchronization, descriptions, and sequence.
The final graph is encoded once when it equals the last turn's graph. A different final graph
retains its own evidence, including a final state that matches an earlier turn. The 80,000-character
prompt limit rejects oversized packets without truncating graph contracts.
For new captures it receives the exact synthesis-visible book and research strings. Older retrieval
telemetry is labeled as incomplete knowledge of the model input; source text beyond the supplied
excerpt cannot certify the answer's grounding. Judge release v6 records this changed evidence contract.

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
