# Prepare Flow Refactor

Last updated: 2026-04-03

## Goal

Status: implemented.

Add an explicit frontend/backend readiness flow for Cloud Run cold starts.

The user should not hit `Send` against a sleeping backend and wait blindly.

Instead:

- the chat draft remains editable
- send is disabled while backend readiness is unknown or stale
- the user clicks `Prepare`
- the frontend wakes the backend and shows progress
- send becomes available only after readiness succeeds

## Why

With Cloud Run `min instances = 0`, cold starts are part of the architecture.

This refactor turns cold start from a hidden failure mode into an explicit user action.

That is better UX than:

- hanging on first chat send
- timing out on first message
- pretending the service is always warm

## UX Contract

### Default State

- input text area is editable
- send button is disabled
- a `Prepare` button appears to the right of the chat input
- helper text explains that the study backend is asleep until prepared

### Preparing State

After click:

- `Prepare` becomes loading / disabled
- send stays disabled
- input stays editable
- show honest progress text like:
  - `Starting study backend…`
  - `Loading retrieval index…`
  - `Almost ready…`

### Ready State

After readiness succeeds:

- `Prepare` disappears or changes to a passive ready state
- send becomes enabled
- draft text remains intact

### Stale State

If readiness has not been confirmed recently:

- frontend returns to readiness unknown
- user must prepare again before sending

We should use a simple local freshness window rather than trying to know exactly whether Cloud Run is still warm.

## Backend Changes

### 1. Dedicated Prepare Endpoint

Add a lightweight endpoint such as:

- `GET /api/prepare`

It should return success only when the backend is actually ready for chat.

Ready means at least:

- app boot complete
- FAISS resources loaded
- required shared state available

Suggested response:

```json
{
  "status": "ready",
  "faiss_loaded": true
}
```

### 2. Health vs Prepare

Current `/health` is mainly operational.

Keep `/health` for infrastructure checks.
Add `/api/prepare` for frontend readiness semantics.

That keeps the contracts clean:

- `/health` says service process is alive
- `/api/prepare` says user-facing chat dependencies are ready

### 3. Optional Readiness Metadata

Useful optional fields:

- `status`
- `faiss_loaded`
- `ready_at`
- `backend_mode`

No fake progress percentages. The frontend should infer progress stages from request lifecycle, not invented backend counters.

## Frontend Changes

### 1. Readiness State Machine

Add a small explicit state:

- `unknown`
- `preparing`
- `ready`
- `error`

### 2. Draft Handling

Do not lock the text area entirely.

Allow:

- typing before readiness
- editing while preparing

Do not allow:

- sending while not ready

### 3. Freshness Window

Persist a lightweight local timestamp for recent readiness.

Example behavior:

- if prepared successfully in the last 10–12 minutes, treat backend as probably warm
- otherwise return to `unknown`

This is a UX optimization, not a correctness guarantee.

### 4. Error Handling

If prepare fails:

- keep draft text
- show retry action
- keep send disabled
- show a short plain-English error

## Implemented Shape

- `GET /api/prepare` returns ready only when the knowledge base is actually loaded
- frontend keeps the draft editable
- send remains disabled until readiness succeeds
- readiness is cached locally for a short freshness window
- thread loading is gated behind readiness so page load does not accidentally wake the backend

## Suggested Implementation Order

1. Add backend `/api/prepare`
2. Add frontend readiness state machine
3. Add `Prepare` button and disabled-send behavior
4. Add loading and retry UI
5. Add freshness timestamp handling
6. Add tests

## Tests

### Backend

- `/api/prepare` returns ready when FAISS is loaded
- `/api/prepare` fails cleanly if resources are unavailable

### Frontend

- send disabled when readiness is unknown
- clicking `Prepare` moves state to preparing
- success enables send without clearing draft
- failure preserves draft and shows retry
- stale readiness returns to unknown after freshness window

## Non-Goals

- not trying to detect exact container liveness from the browser
- not keeping a permanent warm heartbeat
- not hiding cold starts behind a fake immediate send

## Success Criteria

The user experience should feel like:

- `I know the backend is asleep`
- `I can wake it deliberately`
- `I can see that it is warming up`
- `I only send once the system is actually ready`

That is the intended cost-first Cloud Run UX.
