# Current Architecture

Last updated: 2026-04-03

This is the current source of truth for the working prototype.

## Runtime Overview

- `frontend/`
  - React + TypeScript + D3
  - authenticated client
  - SSE-driven chat + graph UI
- `backend/`
  - FastAPI
  - explicit `asyncio` agent pipeline
  - Supabase-backed user/thread/message persistence
  - FAISS-backed retrieval loaded at startup
- `ingestion/`
  - PDF chunking, embedding, FAISS artifact generation
- `infra/terraform/gcp/`
  - Cloud Run + Artifact Registry + Secret Manager

## Request Flow

1. frontend authenticates with Supabase OTP
2. frontend prepares the backend when Cloud Run may be cold
3. frontend sends `POST /api/chat`
4. backend runs:
   - route
   - RAG
   - optional research
   - graph generation
   - synthesis
   - async node enrichment
5. backend streams typed SSE events back to the browser
6. backend persists the completed turn after successful generation

## Important Clarifications

- The current runtime is **not** using LangGraph as the execution engine.
- The transport is **SSE over fetch**, not WebSocket.
- The persistence model is **Supabase-backed threads/messages**, not browser `session_id` ownership.
- The deploy target is **Cloud Run** (backend) + **Vercel** (frontend).

## Primary Code Paths

- backend entrypoint:
  - [backend/main.py](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/backend/main.py)
- chat streaming:
  - [backend/api/sse_handler.py](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/backend/api/sse_handler.py)
- agent orchestration:
  - [backend/agent/graph.py](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/backend/agent/graph.py)
- frontend app shell:
  - [frontend/src/App.tsx](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/frontend/src/App.tsx)
- frontend SSE client:
  - [frontend/src/services/sse.ts](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/frontend/src/services/sse.ts)

## Historical Docs

The older spec in [docs/superpowers/specs/2026-03-31-ai-study-agent-design.md](/Users/yangyuqing/Desktop/Coding%20Projects/Agent/docs/superpowers/specs/2026-03-31-ai-study-agent-design.md) is useful for design history, but it is not the current runtime contract.
