import uuid

from agent.state import AgentState, GraphData
from graph.artifacts import load_canonical_graph_cached
from graph.runtime import select_canonical_graph


async def graph_worker_node(state: AgentState, tools: list) -> AgentState:
    """
    Select a bounded canonical graph from retrieved book chunks.

    The graph worker intentionally does not call the LLM. If canonical evidence is
    too weak, it abstains and lets the caller preserve the existing graph.
    """
    _ = tools
    send = state["send"]
    await send({"type": "worker_status", "worker": "graph", "status": "Selecting graph…"})

    try:
        artifacts = load_canonical_graph_cached()
        graph = select_canonical_graph(
            query=state.get("user_message", ""),
            rag_chunks=state.get("rag_chunks", []),
            artifacts=artifacts,
        )
        return {**state, "graph_data": _attach_graph_version(graph)}
    except Exception as exc:
        print(f"[graph_worker] Unhandled error: {type(exc).__name__}: {exc}")
        return {**state, "graph_data": None}


def _attach_graph_version(graph: GraphData | None) -> GraphData | None:
    if graph is None:
        return None
    stamped = dict(graph)
    stamped["version"] = str(uuid.uuid4())
    return stamped
