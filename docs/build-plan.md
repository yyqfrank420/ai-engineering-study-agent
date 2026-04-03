# Build Plan — AI Engineering Study Agent

Last updated: 2026-04-02

## Status Key
- `[x]` Complete
- `[~]` Complete with enhancements beyond original spec
- `[ ]` Not started

---

## Phase 1: Ingestion Pipeline
Build locally. Run once per book. Output is the FAISS index files that the backend loads.

- [x] **1.1** Scaffold `ingestion/` folder + `requirements.txt`
- [x] **1.2** `ingestion/config.py` — chunk sizes, paths, book metadata
- [x] **1.3** `ingestion/chunker.py` — pdfplumber → parent + child chunks with metadata
- [x] **1.4** `ingestion/sentence_embedder.py` — all-MiniLM-L6-v2 wrapper
- [x] **1.5** `ingestion/ingest.py` — full pipeline: PDF → chunks → embed → FAISS → `/data/`
- [x] **Verify:** FAISS index written, metadata correct, retrieval tested

---

## Phase 2: Backend
FastAPI + explicit asyncio agent pipeline. Build bottom-up: config → adapters → RAG → storage → agent → API.

- [x] **2.1** Scaffold `backend/` + `requirements.txt` + `Dockerfile`
- [~] **2.2** `backend/config.py` — pydantic-settings for all env vars
  - _Added: `rate_limit_per_minute/hour`, `prompt_injection_threshold`, `agent_timeout_s`, `max_message_bytes`_
  - _Added: `research_results_per_query`, `research_noise_domains` (DDG research agent)_
  - _Added: `supabase_url`, `supabase_anon_key`, `supabase_db_url`, `supabase_jwt_issuer`, `turnstile_secret_key`_
- [~] **2.3** `backend/adapters/llm_adapter.py` — Anthropic SDK wrapper (streaming)
  - _OpenAI added as fallback provider (LangChain swap)_
- [~] **2.4** `backend/adapters/` — auth + DB adapters added
  - _`supabase_auth_adapter.py` — Supabase JWT verification, `get_current_user` dependency_
  - _`database_adapter.py` → replaced by `storage/` layer backed by Supabase Postgres_
- [x] **2.5** `backend/rag/sentence_embedder.py` + `faiss_loader.py` + `faiss_retriever.py`
- [~] **2.6** `backend/storage/` — Supabase-backed persistence
  - _`message_store.py`, `thread_store.py`, `profile_store.py` — write to Supabase tables_
  - _Schema: `profiles`, `chat_threads`, `chat_messages` with RLS policies_
- [~] **2.7** `backend/agent/state.py` — AgentState TypedDict
  - _Added: `complexity`, `graph_mode`, `research_enabled`, `research_context`_
- [~] **2.8** `backend/agent/tools/` — rag_search (k=5), get_section, generate_graph
  - _Edge schema extended: `protocol`, `port`, `description` fields on each edge_
- [~] **2.9** `backend/agent/nodes/` — all workers implemented
  - _orchestrator: synthesis uses 3–5 bullet format, thinking disabled (cost reduction ~4×); injects `research_context` block_
  - _rag_worker: `k` param wired from config_
  - _node_detail_worker: 2 RAG searches per node; `book_refs` extracted via regex; connection context injected_
  - _graph_worker: `_COMPLEXITY_HINTS` for low/prototype/production prefix; injects `research_context` before user question_
  - _**research_worker** (NEW): DuckDuckGo web search via `asyncio.to_thread`; 3 queries per message; noise domain filtering; 6-bullet cap; silent fail on timeout_
- [~] **2.10** `backend/agent/graph.py` — Phase 1 restructured
  - _Phase 1a: RAG worker + research worker run in parallel_
  - _Phase 1b: graph worker runs after (receives both rag_chunks + research_context)_
  - _`graph_mode == "off"`: skips graph worker; `"on"`: forces graph worker regardless of routing_
- [~] **2.11** `backend/api/sse_handler.py` — SSE endpoints
  - _`ChatRequest` extended: `complexity`, `graph_mode`, `research_enabled` with validators_
  - _Pre-flight gates: payload size, rate limiting, prompt injection_
  - _Auth: `Depends(get_current_user)` — requires Supabase bearer token_
- [~] **2.12** `backend/main.py` — FastAPI app + lifespan
- [x] **2.13** `backend/api/auth_route.py` — `/api/auth/verify-otp`, `/api/auth/resend-otp` (Supabase OTP)
- [x] **2.14** `backend/api/thread_route.py` — `/api/threads` CRUD (list, create, get, delete)
- [x] **Verify:** SSE connects, chat pipeline fires, graph + node enrichment stream correctly; 30 backend tests pass

---

## Phase 3: Frontend
React + TS + D3. Build inside-out: types → services → hooks → components → App.

- [x] **3.1** Scaffold `frontend/` with Vite + React + TS
- [~] **3.2** `frontend/src/types/index.ts`
  - _`GraphEdge` extended: `protocol?`, `port?`, `description?`_
  - _`GraphNode` extended: `book_refs?: string[]`_
  - _Added: `ComplexityLevel`, `GraphMode`, `WorkerStatus` (incl. `research`), `ThreadSummary`, `AuthSession`_
- [~] **3.3** `frontend/src/services/sse.ts` — SSE client
  - _Sends `Authorization: Bearer` header; passes `complexity`, `graph_mode`, `research_enabled` in POST body_
- [~] **3.4** `frontend/src/hooks/useAgentStream.ts` + `useGraph.ts`
  - _`sendMessage(content, opts?)` — accepts complexity/graphMode/researchEnabled opts_
  - _`streamStatus` changed from `'connecting'` → `'generating'`_
  - _Accepts `authSession` + `activeThreadId`; exposes `hydrateThread`_
- [~] **3.5** `frontend/src/components/Layout/` — SplitPane + TitleBar
  - _TitleBar: `'generating'` status with violet pulsing dot; `userEmail`, `onLogout`, `onNewChat` props_
- [~] **3.6** `frontend/src/components/Chat/` — MessageList, ChatInput, ContextBar, ThinkingIndicator, **ModeBar**
  - _ThinkingIndicator: full rewrite — labeled worker rows (orchestrator/rag/research/graph) with per-worker colors_
  - _ModeBar (NEW): complexity pills (auto/low/proto/prod), graph toggle (auto/on/off), research toggle (○/◉)_
- [~] **3.7** `frontend/src/components/GraphCanvas/` — D3Graph, NodeDetailPopup, SequenceBar
  - _AWS-style outlined cards, edge hover tooltip, glassmorphism popup_
- [~] **3.8** `frontend/src/App.tsx` — full auth flow
  - _Auth: `AuthScreen` when logged out, loading screen while resolving_
  - _Mode state: `complexity`, `graphMode`, `researchEnabled` — passed to `handleSend`_
  - _Thread management: `loadThread`, `handleNewChat`, `handleLogout`_
- [x] **3.9** `frontend/vercel.json` — Vercel config
- [~] **3.10** `frontend/src/index.css` — design tokens + `@keyframes pulse` for generating dot

---

## Phase 4: Integration + Deploy

- [x] **4.1** Connect frontend SSE URL to backend via env var
- [x] **4.2** Supabase project provisioned (`ai-engineering-agent`, eu-west-2)
  - Schema applied: `profiles`, `chat_threads`, `chat_messages` + RLS policies
  - Connection: session pooler `aws-0-eu-west-2.pooler.supabase.com:5432`
  - **Pending:** Update `.env` with new DB password (user changed it 2026-04-02)
- [~] **4.3** Cloudflare Turnstile — free plan, widgets TBD
  - Local dev test keys available (site: `1x00000000000000000000AA`, secret: `1x0000000000000000000000000000000AA`)
  - **Pending:** Create real widget in Cloudflare dashboard → fill `VITE_TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` in `.env`
- [ ] **4.4** Deploy backend to Cloud Run with `min instances = 0`
  - Use request-based billing and the default public `run.app` URL
  - No load balancer
  - Provision via Terraform only; no console or CLI-only setup
  - Backend cold-starts on demand and loads FAISS during startup
- [x] **4.5** Add frontend `Prepare` flow for cold-start-aware UX
  - Chat draft remains editable
  - Send is disabled until backend readiness succeeds
  - First warm-up call wakes Cloud Run via lightweight readiness endpoint
- [ ] **4.6** Deploy frontend to Vercel
- [ ] **Verify:** E2E — click `Prepare`, wait for readiness, ask "Generate an architecture diagram for the transformer encoder", full pipeline fires

---

## Known Issues / Tech Debt

| Issue | Severity | Notes |
|-------|----------|-------|
| Memory route skips RAG on returning sessions | Medium | Orchestrator routes to "memory" if session history exists, bypassing RAG worker. Workaround: new chat thread. |
| Cold start readiness UX | Medium | Cloud Run with `min instances = 0` is the cost target, so the frontend needs an explicit `Prepare` flow instead of assuming warm backend availability. |
| `uvicorn` start command | Low | `main.py` has no `uvicorn.run()` block — must start with `uvicorn main:app --host 0.0.0.0 --port 8000` |
| Supabase pooler provisioning | Low | New project — pooler may need ~5 min to become available after creation |

---

## Cost Profile (per query, post-optimisation)

| Component | Approx cost |
|-----------|-------------|
| Orchestrator + routing | ~$0.005 |
| RAG (k=5 per search) | ~$0.003 |
| Graph generation | ~$0.008 |
| Node enrichment (parallelised, 2 RAG each) | ~$0.010 |
| Synthesis (no thinking) | ~$0.004 |
| Research worker (DDG, optional) | ~$0.000 (no LLM call) |
| **Total (no research)** | **~$0.025–0.035** |

Infra direction:
- Cost-first target: **Cloud Run with `min instances = 0`**
- UX tradeoff: first active use needs backend warm-up
- Planned mitigation: explicit `Prepare` action in frontend before first send

Previous: ~$0.10/query with `thinking_budget_tokens=5000` on synthesis + `rag_top_k=8`.

---

## Reference
Full design spec: `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md`
Supabase schema: `docs/supabase/schema.sql`
Cloud Run deploy plan: `docs/cloud-run-cost-first.md`
Prepare UX refactor: `docs/prepare-flow-refactor.md`
