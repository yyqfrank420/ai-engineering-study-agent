# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/state.py
# Purpose: Shared state definition for the backend agent pipeline.
#          Every phase reads from and writes to this TypedDict while run_agent()
#          passes the evolving state between nodes.
# Language: Python
# Connects to: all agent nodes, agent/graph.py
# Inputs:  n/a (type definition only)
# Outputs: AgentState TypedDict
# ─────────────────────────────────────────────────────────────────────────────

from typing import Any, NotRequired, TypedDict


class GraphNode(TypedDict):
    id: str
    label: str              # 1-4 word display name
    type: str               # "client" | "service" | "datastore" | "gateway" | "network" | "external"
    technology: str         # specific tech choice, e.g. "Python / FastAPI", "PostgreSQL 15"
    description: str        # 1-sentence responsibility summary (graph worker)
    tier: str | None        # "public" | "private" | None (concept graphs omit this)
    detail: str | None      # enriched book content (Node Detail Workers, Phase 3)


class GraphEdge(TypedDict):
    source: str
    target: str
    label: str              # specific action phrase: "sends query", "streams embeddings"
    technology: str         # transport + format: "HTTPS/JSON", "gRPC/Protobuf", "Kafka"
    sync: str               # "sync" | "async"
    description: str        # 1 sentence: what data flows here


class GraphStep(TypedDict):
    step: int
    nodes: list[str]   # node IDs active at this step
    description: str


class GraphGroup(TypedDict):
    id: str
    label: str         # e.g. "Orchestration Layer"
    nodeIds: list[str] # IDs of member nodes


class GraphData(TypedDict):
    graph_type: str    # "architecture" | "concept"
    title: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    sequence: list[GraphStep]
    groups: NotRequired[list[GraphGroup]]  # semantic layer groupings (optional)
    version: NotRequired[str]              # fresh identifier per generated graph revision


class Chunk(TypedDict):
    text: str
    book: str
    chapter: int | None
    chapter_title: str | None
    section: str | None
    page_number: int


class AgentState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    session_id: str          # thread identifier; field name kept for runtime compatibility
    user_id: str
    user_email: str
    user_message: str
    history: list[dict]      # prior conversation turns (role/content dicts)

    # ── Mode controls (set by the frontend per request) ───────────────────────
    complexity: str          # "auto" | "low" | "prototype" | "production"
    graph_mode: str          # "auto" | "on" | "off"
    research_enabled: bool   # True = run research_worker alongside rag_worker

    # ── Routing ───────────────────────────────────────────────────────────────
    # Set by Orchestrator in Phase 0: "memory" (fast path) or "search" (fan out)
    route: str
    request_id: str

    # ── Worker outputs ────────────────────────────────────────────────────────
    rag_chunks: list[Chunk]         # populated by RAG Worker (Phase 1)
    retrieval_relevance: str        # "strong" | "weak"
    retrieval_notice: str           # explanation shown to the user when book retrieval is weak
    graph_data: GraphData | None    # populated by Graph Worker (Phase 1)
    # True when the graph changed this turn — tells orchestrator to emit graph_data event
    graph_changed: bool
    graph_notice_sent: bool         # True when we've already warned that no graph could be produced
    # Web search results from research_worker (empty string if not run)
    research_context: str

    # ── Final outputs ─────────────────────────────────────────────────────────
    response_text: str              # synthesised response (Phase 2)

    # ── SSE send callback ─────────────────────────────────────────────────────
    # Injected before the graph runs; nodes call this to push events to the browser.
    # Type: Callable[[dict], Awaitable[None]]
    send: Any
    await_search_tool_request: Any  # Callable[[str, float], Awaitable[bool]]
