# Current Architecture

Last updated: 2026-08-16

This is the current runtime contract for the production-quality demo.

## Runtime Overview

- `frontend/`
  - React + TypeScript + D3
  - authenticated, steerable WebSocket chat
  - private candidate rendering, typed progress events, and progressive explanation cards
- `backend/`
  - FastAPI
  - legacy LangGraph orchestration by default, with staged applied create/edit diagnostics behind a feature flag
  - server-owned graph contracts, progressive previews, and deterministic maturity and render checks
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
5. `GRAPH_PIPELINE_MODE=legacy` is the default and rollback path. The `staged` mode selects the
   staged state machine only for applied create and edit requests in the scheduled diagnostic. It
   never mixes stages with a legacy request. Steering or cancellation ends the request-scoped state
   machine before a replacement request begins.
6. Kimi K3 at high effort produces a component wire, then a connection wire. The component wire
   contains the root index, title, assumptions, capabilities, and each component's label, type,
   responsibility, group label, group kind, and primary-flow membership. It does not contain a
   composition layer.
7. The server owns IDs, group records, breadth-first sequence derivation, projection, graph
   versions, selected maturity, exact edit admission, validation, state transitions, and
   persistence. The component-only candidate has no edges. Its render gate emits a reversible
   preview before one Sonnet medium component gate call. The full candidate follows the same render,
   reversible-preview, then connection-gate order. These previews remain nonauthoritative until
   semantic acceptance and persistence. One malformed gate result ends the request. Each layer has at most
   two candidates. A connection retry cannot reopen an accepted component layer.
8. Prototype gates exclude production criteria. Production proof requirements derive from the
   component wire's capabilities. There is no Opus root architecture pass and no final full-model
   gate. Opus low writes the explanation after both gates pass. Deterministic explanation fallback
   keeps an accepted graph publishable when the explanation call fails.
9. The transport atomically persists graph data and its server-only contract before emitting
   authoritative `graph_data` and `done`. `auto` edits inherit stored maturity. A legacy graph with
   no stored contract defaults to prototype. An explicit different depth reruns both semantic stages.
   A bounded edit retains exact record authority during that restage, including locked assumptions
   and prior composition records.
   The prior durable graph is restored after failure, retry exhaustion, steering, stop, timeout, or
   persistence failure. The 90-second prototype first-preview target is an SLO. Generation calls
   use a 130-second timeout, gates use 55 seconds, and the request ceiling includes orchestration
   and private renders.

The model never writes SVG. Its typed graph JSON is an intermediate representation with named
responsibility zones, ordered sequence steps, and runtime/control/feedback/deployment edge classes.
The D3 renderer deterministically compiles that structure into responsive branded SVG, preserving
interaction, accessibility, layout evaluation, and compatibility with previously stored graphs.

The server sends the authoritative 1440 by 960 CSS-pixel evaluation viewport and 11 CSS-pixel
post-fit node-title floor with each private candidate. The renderer chooses horizontal or ranked vertical placement from the
resulting fit scale. A rank-ordered compact layout covers the full 60-node backend safety ceiling
when either ordinary plan would be unreadable. Bottom-lane height is derived from its densest
column. The browser still measures the real SVG. The server rejects overlapping node cards or
responsibility-zone boundaries, clipped nodes or edges, missing required labels, and unreadable
node titles. The non-browser staging client consumes the same criteria from the candidate event,
and its compact fallback covers the same 60-node ceiling. The browser and staging clients reject a
candidate that omits or changes the fixed criteria. The capacity correction passes offline tests and a local Chromium replay of
paid diagnostic `31825436257`; that paid workflow did not emit protected publication success.

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

The staged path gives each active role one explicit owner. Kimi K3 high authors bounded component
and connection wires. Sonnet 5 medium gates each candidate once. The server owns graph mutation,
validation, maturity, and all state transitions. Opus 5 low writes the explanation stream and has a
deterministic fallback. The no-retry path makes five application model calls. The bounded maximum
is nine. Renderer infrastructure failures add no model calls. Retrieval and the standing checklist
do not add model calls.

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
- `GRAPH_PIPELINE_MODE=legacy` is the default. The scheduled diagnostic may select `staged` for an
  applied create or edit request. The legacy whole-graph repair loop remains the rollback path and
  cannot mix writes with a staged request.
- The live staging harness also uses the WebSocket protocol. It submits a bounded contract render
  so deployment model evaluations cannot bypass the diagram gate; the product browser remains the
  authoritative evaluator of the actual D3 canvas at the fixed server-contract viewport.

## Primary Code Paths

- backend entrypoint: `backend/main.py`
- WebSocket protocol: `backend/api/chat_websocket.py`
- compatibility SSE endpoints: `backend/api/sse_handler.py`
- orchestration: `backend/agent/graph.py`
- applied designer: `backend/agent/nodes/graph_worker.py`
- independent reviewer: `backend/agent/nodes/graph_critic.py`
- stable review frame: `backend/agent/architecture_playbook.py`
- sequential architecture and review roles: `backend/agent/nodes/architecture_workers.py`
- browser evaluation channel: `backend/api/diagram_evaluation_channel.py`
- progressive explanation stream: `backend/agent/explanation_blocks.py`
- frontend transport: `frontend/src/services/agentTransport.ts`
- frontend stream state: `frontend/src/hooks/useAgentStream.ts`

The older spec in `docs/superpowers/specs/2026-03-31-ai-study-agent-design.md` is design history,
not the current runtime contract.
