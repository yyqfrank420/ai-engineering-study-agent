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

## Notes

- `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is a historical design snapshot, not the current source of truth.
- Legacy session-scoped storage now lives under `backend/legacy/storage/` for compatibility tests only; the production path is thread-based and authenticated.
