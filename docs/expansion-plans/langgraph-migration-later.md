# LangGraph Migration Later

Last updated: 2026-04-03

## Decision

Do not migrate the backend orchestration to LangGraph before the first commit or first deploy.

The current runtime is an explicit `asyncio` pipeline in `backend/agent/graph.py`. It is small enough to reason about, currently tested, and already integrated with:

- SSE streaming
- stop/cancel behavior
- Supabase-backed persistence
- graph/no-graph fallback notices
- optional research handoff
- post-response node enrichment

Swapping orchestration frameworks right now would be a high-risk refactor for anticipated complexity, not a fix for a current blocker.

## Current Runtime Shape

The backend currently runs this flow:

1. route
2. retrieve book context
3. optionally retrieve broader web context
4. generate or update the graph
5. synthesize and stream the response
6. enrich graph nodes asynchronously

This is still manageable as ordinary Python control flow.

## When LangGraph Starts Making Sense

Revisit the migration when one or more of these become real requirements:

- durable checkpointing / resume mid-run
- multi-step retries with stateful recovery
- human approval / interrupt steps
- more complex conditional branching
- long-running workflows across requests
- multiple agent subflows that are hard to reason about linearly
- richer light-GraphRAG or evaluation workflows with explicit state transitions

## Expected Benefits Later

If the app reaches that point, LangGraph would likely help with:

- explicit node/edge orchestration instead of hand-managed control flow
- better visibility into branching and loop behavior
- easier evolution toward resumable stateful workflows
- cleaner separation between runtime graph definition and node implementations

## Migration Constraints

If we migrate later, preserve these current behaviors:

- graph data can be emitted before the final text finishes
- `Stop` must actually stop server-side work
- persistence happens only after successful completion
- graph warnings and retrieval notices remain first-class events
- stale node-enrichment results must not land on a newer graph

These are product behaviors, not implementation details.

## Proposed Migration Order

1. Freeze current runtime behavior with stronger integration tests.
2. Extract node contracts more cleanly:
   - route
   - rag
   - research
   - graph
   - synthesize
   - enrich
3. Recreate the same flow in LangGraph without changing UX contracts.
4. Run both implementations behind the same tests.
5. Only then switch the app entrypoint to the LangGraph-backed runtime.

## Non-Goal

Do not introduce LangGraph just because the architecture is “agent-like.”

The trigger should be real workflow complexity, not fashion.
