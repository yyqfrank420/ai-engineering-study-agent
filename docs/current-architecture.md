# Current Architecture

Last updated: 2026-07-21

This is the current runtime contract for the production-quality demo.

## Runtime Overview

- `frontend/`
  - React + TypeScript + D3
  - authenticated, steerable WebSocket chat
  - private candidate rendering, typed progress events, and progressive explanation cards
- `backend/`
  - FastAPI
  - request-scoped LangGraph orchestration
  - sequential applied-design enrichment and challenge roles, plus a screenshot-aware critic with one bounded semantic revision
  - Supabase-backed user/thread/message persistence
  - FAISS-backed book retrieval loaded by a non-blocking readiness task
- `ingestion/`
  - PDF chunking, embedding, and checksum-pinned FAISS artifact generation
- `infra/terraform/gcp/`
  - Cloud Run + Artifact Registry + Secret Manager

## Request and Steering Flow

1. The frontend authenticates with Supabase and opens `WS /api/chat/ws`.
2. The bearer token is sent in the first frame, never in the WebSocket URL.
3. The client sends a `start` command with thread and mode controls.
4. LangGraph routes, restores terse follow-ups to the full design intent, and searches that canonical
   query rather than the raw fragment. Book retrieval and enabled web research run in parallel; the
   product UI enables web grounding by default while retaining an explicit book-only control. Their
   results are combined with the stable review frame covering platform boundaries, model lifecycle,
   data/memory, evaluation, safety, idempotent writes, latency/cost, reliability, and deployment.
5. The Architect enriches a terse seed into one explicit product brief: actors, authoritative inputs,
   controlled decisions/actions, outputs, measures, assumptions, evidence provenance, and runtime.
   The Challenger then audits that exact interpretation before the graph worker integrates it into
   domain responsibilities and directional flows.
6. Deterministic architecture checks run first. A surviving candidate is sent as `graph_candidate`
   and rendered off-screen at the user's real graph-pane dimensions. The browser returns a bounded,
   version-checked screenshot and layout report over idempotent WebSocket chunks.
7. The critic judges architecture correctness plus novice clarity, logical flow, succinctness,
   readability, and MECE-ish coverage from the actual render. A semantic rejection can receive one
   typed Opus 5 low-effort patch, with at most two workflow revisions. A malformed patch gets one
   medium-effort retry; both attempts
   change only named nodes, edges, or bounded graph collections;
   unchanged topology is preserved and the complete result passes deterministic validation again.
   Node and edge budgets are explicit in both generation lanes; over-budget topology and semantic
   no-op patches fail visibly instead of being silently truncated by output order.
   A second failure suppresses the diagram. Geometry-only failures are terminal because layout
   belongs to the deterministic renderer, so they never spend another model call on a topology rewrite.
8. The accepted graph remains private while one Opus 5 high-effort call completes its explanation cards. The
   server then emits `graph_data` followed by the buffered cards, so an unfinished walkthrough never
   reveals a new diagram. Pause can still hold card reveal in the browser without another model call.
9. The transport persists the completed turn before emitting `done`.

The model never writes SVG. Its typed graph JSON is an intermediate representation with named
responsibility zones, ordered sequence steps, and runtime/control/feedback/deployment edge classes.
The D3 renderer deterministically compiles that structure into responsive branded SVG, preserving
interaction, accessibility, layout evaluation, and compatibility with previously stored graphs.

FastAPI becomes available after database initialisation, then loads the FAISS artifacts and index in
a background thread. `GET /api/prepare` reports the current server-owned milestone and completed/total
units; the frontend renders that exact progress and never advances it with an elapsed-time animation.

Every production frontend turn includes a UUID `client_request_id`. Completed user/assistant
pairs are unique on that key at the database boundary, and a network retry replays the stored
assistant response. The temporary SSE compatibility endpoint still tolerates legacy callers that
omit the key; the WebSocket product path always supplies it.

Thread admission, active streams, chat requests, OTP/internal login attempts, and public analytics
capture use shared transactional storage. Rate-limit identifiers are HMAC-derived before
persistence, so Cloud Run scale-out neither resets the limits nor stores raw emails/IPs in the
limiter table.

The normal applied-design path uses Opus 5 with role-specific effort: high for Architect and
Challenger, low for constrained graph integration, medium for the first independent
architecture/render review, and high for the explanation stream. Each failed semantic quality pass
can add a low-effort compact patch and one low-effort bounded re-review, up to two revisions. A malformed patch or
structurally invalid first draft may use its medium-effort repair role once;
renderer-only failures add no model calls. Retrieval and the standing checklist do not add model calls.
Ordinary user-requested refinements to an existing graph remain medium effort.

During steps 4-7 the client may send `steer`. The server cancels the active workflow, emits
`response_reset`, and restarts with the steering correction folded into the same turn. `stop`
cancels server-side work. Steering is content-filtered, size-bounded, and capped at three updates.

## Why Both LangGraph and asyncio Exist

LangGraph owns workflow state, branches, and the review/revision loop. Ordinary `asyncio` remains
the correct local primitive inside nodes for parallel RAG/research I/O and transport cancellation.
The distinction is orchestration versus concurrency, not framework versus no framework.

## Compatibility Boundary

- `POST /api/chat` remains as a temporary SSE compatibility endpoint.
- `POST /api/node-selected` remains SSE because it is a one-shot server-to-client stream.
- New chat functionality belongs on the WebSocket protocol.
- Durable LangGraph checkpointing is intentionally not enabled yet: live callbacks, tasks, and
  tool bindings are request context rather than persistent graph data. Moving those handles into
  runtime context is the prerequisite for a database checkpointer.
- The live staging harness also uses the WebSocket protocol. It submits a bounded contract render
  so deployment model evaluations cannot bypass the diagram gate; the product browser remains the
  authoritative evaluator of the actual D3 canvas at the user's viewport size.

## Primary Code Paths

- backend entrypoint: `backend/main.py`
- WebSocket protocol: `backend/api/chat_websocket.py`
- compatibility SSE endpoints: `backend/api/sse_handler.py`
- orchestration: `backend/agent/graph.py`
- applied designer: `backend/agent/nodes/graph_worker.py`
- independent reviewer: `backend/agent/nodes/graph_critic.py`
- stable review frame: `backend/agent/architecture_playbook.py`
- parallel design roles: `backend/agent/nodes/architecture_workers.py`
- browser evaluation channel: `backend/api/diagram_evaluation_channel.py`
- progressive explanation stream: `backend/agent/explanation_blocks.py`
- frontend transport: `frontend/src/services/agentTransport.ts`
- frontend stream state: `frontend/src/hooks/useAgentStream.ts`

The older spec in `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is design history,
not the current runtime contract.
