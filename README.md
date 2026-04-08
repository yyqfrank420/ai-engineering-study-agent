# AI Engineering Study Agent

Graph-guided study companion for *AI Engineering* by Chip Huyen.

## Current Stack

- `frontend/`
  - React + TypeScript + D3
  - Vercel-targeted frontend
- `backend/`
  - FastAPI
  - explicit `asyncio` agent pipeline
  - Supabase-backed persistence
  - FAISS-backed retrieval loaded at startup
- `ingestion/`
  - one-time PDF chunking / embedding / FAISS build
- `infra/terraform/gcp/`
  - Cloud Run + Artifact Registry + Secret Manager provisioning

## Runtime Model

The current backend does **not** use LangGraph as the execution engine.

It uses an explicit pipeline in `backend/agent/graph.py`:

1. route
2. retrieve
3. optional research
4. graph generation
5. response synthesis
6. async node enrichment

Future LangGraph migration notes live in [docs/langgraph-migration-later.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/langgraph-migration-later.md).

## Deployment Direction

Cost-first deploy target:

- frontend on Vercel
- backend on Cloud Run with `min instances = 0`
- explicit frontend `Prepare` flow before first send in a cold session

Relevant docs:

- [docs/README.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/README.md)
- [docs/current-architecture.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/current-architecture.md)
- [docs/cloud-run-cost-first.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/cloud-run-cost-first.md)
- [docs/prepare-flow-refactor.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/prepare-flow-refactor.md)
- [docs/build-plan.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/build-plan.md)

## Shipped Features

- **Graph layout persistence** (2026-04-05): Pan/zoom + node positions saved per graph, restored on session reload. Debounced 400ms frontend cache → `PUT /api/threads/{id}/graph`.
- **Cold-start UX contract**: Explicit `Prepare` button unlocks Send after backend is ready.
- **Three-way routing**: SIMPLE (direct Haiku) / MEMORY (session history) / SEARCH (RAG + graph + research).
- **D3 architecture diagram**: Interactive graph with step-by-step walkthrough and node detail enrichment.

## Local Development

Backend:

```bash
cd backend
./.venv/bin/pytest -q
uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
npm run build
npm run dev
```

Pre-push sanity check:

```bash
bash scripts/prepush_check.sh
```

If `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are set, that script also runs the same Vercel CLI build path the deploy workflow now gates on.

Staging-style live evals:

```bash
python scripts/run_staging_eval.py \
  --base-url 'https://<backend>.run.app' \
  --email '<allowlisted-email>' \
  --internal-password '<internal-test-password>'
```

The blocking deploy pipeline now uses the same harness against a tagged, no-traffic Cloud Run candidate revision before production traffic is promoted.

## Notes

- `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is a historical design snapshot, not the current source of truth.
- Legacy session-scoped storage now lives under `backend/legacy/storage/` for compatibility tests only; the production path is thread-based and authenticated.
