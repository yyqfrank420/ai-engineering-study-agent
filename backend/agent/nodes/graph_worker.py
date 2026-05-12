import uuid
from typing import Any

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
            query=_graph_query(state),
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


def _graph_query(state: AgentState) -> str:
    message = state.get("user_message", "")
    if not _looks_like_graph_followup(message):
        return message

    prior_user_messages = [
        str(turn.get("content", ""))
        for turn in state.get("history", [])[-8:]
        if turn.get("role") == "user" and turn.get("content")
    ]
    graph_context = _existing_graph_context(state.get("graph_data"))
    return " ".join([*prior_user_messages[-3:], graph_context, message]).strip() or message


def _looks_like_graph_followup(message: str) -> bool:
    text = message.lower()
    return any(
        phrase in text
        for phrase in (
            "expand",
            "all agents",
            "sub-agent",
            "subagent",
            "more detail",
            "go deeper",
            "add nodes",
            "add each",
            "show all",
        )
    )


def _existing_graph_context(graph_data: dict[str, Any] | None) -> str:
    if not graph_data:
        return ""
    labels = [
        str(node.get("label", ""))
        for node in (graph_data.get("nodes") or [])[:8]
        if node.get("label")
    ]
    title = str(graph_data.get("title") or "")
    graph_type = str(graph_data.get("graph_type") or "")
    return " ".join(part for part in [title, graph_type, *labels] if part)
