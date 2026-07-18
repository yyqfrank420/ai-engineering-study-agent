# LangGraph Orchestration Decision

Last updated: 2026-07-18

## Decision

Use LangGraph for the agent workflow. Do not migrate the application to Google ADK.

The earlier decision to keep a linear asyncio pipeline was correct while the runtime only routed,
retrieved, generated, and synthesized once. It stopped being correct when the product required an
independent quality gate, conditional revision, client steering, and future resumability. Those are
workflow-state concerns rather than local concurrency concerns.

## Implemented Shape

`backend/agent/graph.py` now defines explicit nodes and edges for:

- routing and quick answers
- context gathering
- applied or canonical graph construction
- optional search-tool expansion
- independent design review
- one bounded revision or diagram rejection
- response synthesis
- concept-node enrichment

Request-scoped tools remain closure-bound. The public `run_agent(state, tools...)` API and typed
event stream are unchanged, which keeps the HTTP compatibility endpoint and the WebSocket transport
independent of the orchestration engine.

## Why LangGraph Here

- The repository already uses LangChain packages and LangGraph was already a transitive dependency.
- The existing `AgentState` maps directly to a state graph.
- Conditional edges make the quality policy inspectable and testable.
- The application remains model-provider neutral.
- Migration is incremental; retrieval, generation, storage, and UI contracts did not need rewrites.

Google ADK 2 can express graph workflows, but adopting it here would also replace session, event,
agent, and deployment conventions. That is a larger platform migration without a corresponding
product benefit for this repository.

## Deliberate Non-Goal: Checkpointing Today

No durable checkpointer is configured yet. `send`, `await_search_tool_request`, live tool objects,
and transient asyncio tasks are request I/O handles and must never be serialized. A checkpointing
phase should first move those values into LangGraph runtime context, define a reduced durable state,
and then add a Postgres-backed saver with resume and idempotency tests.

## Preserved Product Contracts

- Stop cancels server-side model work.
- Steering resets partial output and cannot create concurrent writers.
- Completed turns persist atomically before `done` on WebSockets.
- Retrieval and graph warnings remain typed events.
- Applied recommendations never receive fabricated book citations.
- A diagram that fails the second quality review is omitted.
