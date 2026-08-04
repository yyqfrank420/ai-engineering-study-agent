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

`backend/agent/graph.py` defines a request-scoped LangGraph workflow:

1. route the request
2. restore terse follow-ups to the canonical design intent, then retrieve book evidence and optional current web context
3. enrich applied-design seeds into one explicit product brief, then challenge that same interpretation
4. integrate their outputs into a domain-specific graph
5. render the candidate privately in the browser and review the real screenshot plus architecture
6. run at most one typed semantic patch and revalidate the complete graph; edge budgets are explicit and over-budget output is rejected rather than positionally truncated, while renderer-only failures never trigger another model call
7. finish the one-call walkthrough privately, then reveal the accepted graph and explanation together

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
- **Unified model quality**: Opus 5 at high effort handles every application model role, including compact graph repairs.
- **D3 architecture diagram**: Interactive graph with step-by-step walkthrough and node detail enrichment.
- **Protected live evaluation**: Browser journeys, deterministic graph contracts, and reviewed semantic rubrics run against isolated no-traffic Cloud Run revisions.
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
deterministic invariants plus reviewed semantic rubrics. The protected corpus is
approved; diagnostic runs can select individual unresolved cases, while the manual
override fails closed unless its evidence covers every protected PR case exactly once.
See
[docs/quality-system.md](docs/quality-system.md) for activation and operations.

## Maintainer

Maintained by [Frank Yang](https://github.com/yyqfrank420).

## Notes

- `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is a historical design snapshot, not the current source of truth.
