# Current Architecture

Last updated: 2026-08-14

This is the current runtime contract for the production-quality demo.

## Runtime Overview

- `frontend/`
  - React + TypeScript + D3
  - authenticated, steerable WebSocket chat
  - private candidate rendering, typed progress events, and progressive explanation cards
- `backend/`
  - FastAPI
  - request-scoped LangGraph orchestration
  - applied-design enrichment, direct graph construction, and a screenshot-aware critic with up to two bounded semantic repairs
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
5. Kimi authors the initial graph draft from the request, selected review depth, retrieved evidence,
   and server-owned topology contract. At prototype depth, the architect and critic review that exact
   candidate in parallel after render. At low and production depth, Architect reviews first. Its
   diagram requirements become blocking critic context only at production depth.
6. Deterministic graph checks run first. A surviving candidate is sent as `graph_candidate`
   and rendered off-screen at the server's fixed evaluation viewport. The browser returns a bounded,
   version-checked screenshot and layout report over idempotent WebSocket chunks. The server decides
   admission from that report. The model never owns layout or render acceptance.
   An initial topology rejection can be corrected once with exact validation feedback in the same
   stage when the remaining preview capacity is at least the observed first-attempt duration.
   Otherwise generation fails closed with the original validation error.
7. The critic judges four disjoint artifact layers: components, connections, composition, and the
   rendered artifact. Each layer has its own hard pass gate. `novice_clarity` is advisory and cannot
   reject a candidate or grant repair authority. Sonnet returns a fixed scorecard of
   rubric codes and record indexes; the server expands them into exact selectors and read-only
   context. The server owns the title, groups, and sequence repair profile for `authored_composition`;
   critic and patch output cannot widen it. Composition selectors and append counts survive
   canonicalization only when their exact field remains authorized by that server-owned profile. A
   production topology result is a semantic attestation bound to a structurally validated directed
   witness. The server validates cited records and reachability. The graph contract does not carry
   typed semantic roles that could prove each safety guarantee without model judgment.
   Reviewer-owned `not_applicable` remains a known production risk until the product defines a
   server-owned applicability contract and typed node roles and edge relations. A
   local semantic rejection can receive at most two
   successful Kimi K3 high typed repair rounds against exact failed records, including disconnected
   record regions. Uncited records stay locked.
   Component changes reopen component, connection, and composition review. Edge changes reopen
   connection and composition review. Composition-only changes reopen composition review. A
   transition from prototype to production depth reopens connection and composition review and
   requires a fresh complete topology-proof set. An invalid
   patch may receive one error-informed critic-contract correction before the patch is retried.
   Exact connection-addition obligations are authoritative for added edges. Critic component repairs
   use exact existing-node update rows only; `existing_node_operations` must name the exact node,
   fields, and values. Critic-driven node deletion is not permitted. Existing-edge repairs declare
   exact `update`, `remove`, or `replace` operations, and replace
   operations cite exact replacement obligations. One repair may combine edges incident to new components
   with exact existing-to-existing edges. Every added edge must
   match an authorized source, target, and normalized label; every new component remains attached
   to an existing graph-anchored region.
   Each scorecard stores its reviewed graph snapshot. Every post-patch review derives prior server
   obligations as resolved or still failing from the
   current typed blocker identities. The model does not classify server-owned obligation state. A
   still-failing typed blocker with the same exact repair fingerprint cannot consume a second repair
   and fails closed. A
   graph-caused render failure can share the patch when an editable layer identifies the cause. A
   render-only failure, global design failure, or failed post-patch review suppresses the diagram.
   The entire turn has a four-call Sonnet critic ceiling. Protocol-format and patch-contract
   corrections have separate one-call counters that survive WebSocket steering restarts. Every
   critic dispatch makes one provider attempt, so the four-call ceiling also caps outbound Sonnet
   requests at four.
   Internal-test diagnostics cover private-render, deterministic-layout, preview-transport, critic,
   and outer critic-timeout exits. They record only counters, selected depth, locked and reopened
   layers, finding codes, blocker IDs, opaque fingerprints, and correction outcomes. They exclude
   prompts, model text, and graph records. Published user refinements use the same typed patch boundary. The
   model chooses graph size, groups, and primary runtime-sequence membership from the design. The server derives sequence
   stages as shortest directed distances from the root across selected components using tree edges
   and explicit runtime links. The topology prompt states node and edge safety ceilings, and provider
   schemas plus local validation enforce them to protect persistence and rendering. Invalid topology
   is rejected without deleting authored responsibilities or paths. Browser capture or geometry
   failure stops publication.
8. After deterministic graph and browser-render checks pass, the server emits a reversible
   `graph_preview` while semantic review continues. The transport retains the prior durable graph and
   restores it after review failure, rejected repair, steering, stop, timeout, persistence failure,
   or connection failure. A reviewed turn streams its explanation cards, persists, and then commits
   the accepted graph with authoritative `graph_data`. Pause can still hold card reveal in the
   browser without another model call.
   Prototype first-preview latency has a 90-second product SLO. This is a measurement target, not a
   runtime cutoff. Production retains the 170-second preview allowance and the full fail-closed
   review window. Semantic review stays request-scoped; background replacement is deferred until
   graph publication has durable job ownership and compare-and-set versioning.
9. The transport persists the completed turn before emitting `done`.

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

The applied-design path gives each active role one explicit owner. Kimi K3 high creates the initial
graph topology and applies typed patches to local critic failures and published user refinements.
Opus 5 medium audits the initial candidate and supplies production-only diagram requirements to the
critic. Repairs do not rerun Architect.
Sonnet 5 medium reviews every graph candidate and revision. The graph workflow does not invoke the
challenger worker. Opus 5 low writes the explanation stream. Renderer infrastructure failures add no
model calls.
Retrieval and the standing checklist do not add model calls.

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
