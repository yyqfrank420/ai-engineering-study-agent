# AI Engineering Study Agent

Production-oriented, graph-guided study companion for *AI Engineering* by Chip Huyen.

## Current Stack

- `frontend/`
  - React + TypeScript + D3
  - Vercel-targeted frontend
- `backend/`
  - FastAPI
  - LangGraph state-machine orchestration
  - steerable WebSocket chat transport
  - Supabase-backed persistence
  - FAISS-backed retrieval loaded in a non-blocking readiness task
- `ingestion/`
  - one-time PDF chunking / embedding / FAISS build
- `infra/terraform/gcp/`
  - Cloud Run + Artifact Registry + Secret Manager provisioning
  - immutable, evaluated-image promotion to production

## Runtime Model

`backend/agent/graph.py` defines a request-scoped LangGraph workflow. Applied graph
creation and edits use `GRAPH_PIPELINE_MODE=staged` by default:

1. route the request
2. restore terse follow-ups to the canonical design intent, then retrieve book evidence and optional current web context
3. use Kimi K3 at high effort to propose component responsibilities, assumptions, and capabilities
4. assign IDs, validate and render a reversible component preview, then run the Sonnet medium component gate
5. generate connections against the accepted components, validate the full candidate and its browser render, then run the Sonnet medium connection gate
6. allow one correction per stage; a connection correction keeps the accepted components fixed
7. write the walkthrough, atomically persist the accepted graph and its server-only contract, then publish the authoritative graph and completed response

When the requested workflow is unclear, the component planner can ask up to three
questions and stop before connection generation or review. Replies continue the
design using the prior user requirements. A failed creation retains its failure
notice and can still answer independent explanatory questions within the remaining
request deadline.

Scoped edits generate additions and authorized field updates. The server preserves locked
records, retained IDs, and unaffected presentation. Prior semantic approval is reused only
when graph and reviewer fingerprints and accepted context still match. Review covers the
edit and its effects on dependencies. Failure preserves the prior approved graph, or
withholds a failed new graph.
Set `GRAPH_PIPELINE_MODE=legacy` explicitly to roll back to the whole-graph review and repair
pipeline. Concept diagrams keep their existing route.

Chat runs over `/api/chat/ws`. The first frame authenticates the connection; subsequent
`start`, `steer`, bounded diagram-evaluation frames, and `stop` commands share the same channel. A steer cancels the draft,
clears partial output, and restarts the bounded workflow with the correction included.
The old POST/SSE chat endpoint remains temporarily as a compatibility path; one-shot node
suggestions still use HTTP streaming.

The orchestration decision and remaining checkpointing work are recorded in
[docs/expansion-plans/langgraph-migration-later.md](docs/expansion-plans/langgraph-migration-later.md).

## Deployment Direction

Cost-first deploy target:

- frontend on Vercel
- backend on Cloud Run with `min instances = 0`
- explicit frontend `Prepare` flow before first send in a cold session
- exact-tree image approval before production traffic promotion

Relevant docs:

- [docs/README.md](docs/README.md)
- [docs/current-architecture.md](docs/current-architecture.md)
- [docs/expansion-plans/cloud-run-cost-first.md](docs/expansion-plans/cloud-run-cost-first.md)
- [docs/expansion-plans/prepare-flow-refactor.md](docs/expansion-plans/prepare-flow-refactor.md)
- [docs/build-plan.md](docs/build-plan.md)

## Shipped Features

- **Graph layout persistence** (2026-04-05): Pan/zoom + node positions saved per graph, restored on session reload. Debounced 400ms frontend cache → `PUT /api/threads/{id}/graph`.
- **Cold-start UX contract**: Explicit `Prepare` button shows real server milestones and unlocks Send only after the retrieval index is ready.
- **Three-way routing**: SIMPLE (Opus 5 high effort) / MEMORY (session history) / SEARCH (RAG + architecture workflow).
- **Explicit design roles**: Kimi K3 high generates staged components and connections, Sonnet 5 medium reviews each stage, Opus 5 low writes the applied-design walkthrough, and Sonnet 5 high owns the protected semantic judge.
- **D3 architecture diagram**: Interactive graph with step-by-step walkthrough and node detail enrichment.
- **Protected live evaluation**: Browser journeys, deterministic graph contracts, and reviewed semantic rubrics run against isolated no-traffic Cloud Run revisions.
- **Bounded graph publication**: Each stage permits at most two candidates. Both semantic gates and browser render checks must pass before publication. Scoped edits preserve graph identity and locked records; rejected edits retain the approved graph instead of creating a replacement.
- **Selective evidence reuse**: Audited per-case evidence composition avoids repeating already-passing paid evaluations while requiring exact evidence for the unresolved case.
- **Immutable production delivery**: Production deploys only the approved Artifact Registry digest for the exact Git tree, smokes it without traffic, then promotes that revision.

## Local Development

Backend:

```bash
cd backend
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
./.venv/bin/python -m uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm run build
npm run dev
```

Pre-push sanity check:

```bash
./scripts/ci offline
```

`scripts/prepush_check.sh` is a compatibility wrapper around that exact command.
GitHub reads the same versioned manifest and partitions it with
`./scripts/ci offline --group <name>`; test commands and path-impact policy are
not duplicated in workflow YAML.

The default ingestion checks use an injected fake embedder and the tracked FAISS artifacts.
Set `AI_ENGINEERING_PDF_PATH` to exercise source-PDF parsing, and set
`RUN_INGESTION_MODEL_TESTS=1` only when intentionally loading the real local model.

If `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are set, that script also runs the same Vercel CLI build path the deploy workflow now gates on.

Protected staging evaluation commands:

```bash
./scripts/ci browser --suite pr --target http://localhost:5173 \
  --output artifacts/live-eval/browser-results.json
./scripts/ci live --suite pr --target 'https://<candidate>.run.app' \
  --input artifacts/live-eval/browser-results.json \
  --output artifacts/live-eval/live-results.json
```

The GitHub gate supplies the protected credentials, starts a frontend wired to the
no-traffic candidate, captures the real WebSocket/browser journey, and then applies
deterministic invariants plus anchored semantic rubrics. Human corpus review and judge
calibration are optional. Automated failures block; borderline judgments stay visible
as nonblocking findings. Diagnostic runs can select individual unresolved cases.
Evaluation and release provenance binds the content commit, Git tree, and immutable
image digest across synthetic PR merge refs and later squash merges. Selective semantic
replay reuses only authenticated, successful graph-free cases; runtime-affected cases
rerun as scheduled diagnostics. Scheduled evaluation now reports a missing image tag in
preflight, while a manually dispatched full or diagnostic run can build an ephemeral
image from the exact requested tree. The staged pipeline permits one correction per layer, and failed admission preserves
the approved graph. The legacy whole-graph repair loop remains available through explicit rollback.
These controls do not imply that paid validation or a pending production
deployment has completed. See [docs/quality-system.md](docs/quality-system.md) for the
full evidence, replay, and deployment procedures.

The [2026-09-11 failure audit](docs/failure-audit-2026-09-11.md) reconciles all 55 failed
single-case graph-expansion diagnostics with their available evidence. Scoped staged edits now
generate additions and authorized field updates while the server preserves locked records.
Generation and review share their acceptance criteria. Required live status follows automated
evaluation results; offline success does not replace live evaluation.
Scoped review verifies prior approvals against graph and reviewer fingerprints and checks each
edit's effects on dependencies. Edge edits preserve authored presentation; node deletion cleans
only affected sequence memberships. Scheduled failures stay failed and retain review evidence
with deployment identity for 90 days.

## Maintainer

Maintained by [Frank Yang](https://github.com/yyqfrank420).

## Notes

- `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is a historical design snapshot, not the current source of truth.
