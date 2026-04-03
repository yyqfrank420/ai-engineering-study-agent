import asyncio

from agent.nodes.graph_worker import graph_worker_node
from agent.nodes.node_detail_worker import enrich_all_nodes
from agent.nodes.rag_worker import rag_worker_node
from agent.nodes.research_worker import research_worker_node
from agent.state import AgentState
from config import settings


def should_run_graph_worker(state: AgentState, existing_graph: dict | None) -> bool:
    graph_mode = state.get("graph_mode", "auto")

    if graph_mode == "off":
        return False
    if graph_mode == "on":
        return True
    if state["route"] == "search":
        return True
    return existing_graph is None


async def apply_graph_worker(state: AgentState, graph_tools: list) -> AgentState:
    existing_graph = state.get("graph_data")
    if not should_run_graph_worker(state, existing_graph):
        return state

    graph_state = await graph_worker_node(state, graph_tools)
    new_graph = graph_state.get("graph_data")
    if new_graph is None:
        if (
            existing_graph is None
            and state.get("route") == "search"
            and not state.get("graph_notice_sent")
        ):
            await state["send"]({
                "type": "graph_notice",
                "message": (
                    "I found enough related material to explain this, but not enough grounded detail "
                    "from the book to draw a trustworthy graph for this exact question."
                ),
            })
        return {
            **state,
            "graph_data": existing_graph,
            "graph_changed": False,
            "graph_notice_sent": state.get("graph_notice_sent", False) or (
                existing_graph is None and state.get("route") == "search"
            ),
        }

    return {
        **state,
        "graph_data": new_graph,
        "graph_changed": True,
        "graph_notice_sent": state.get("graph_notice_sent", False),
    }


async def run_search_phase(state: AgentState, rag_tools: list) -> tuple[AgentState, asyncio.Task | None]:
    graph_mode = state.get("graph_mode", "auto")
    search_tool_wait_task = None

    effective_route = "search" if graph_mode == "on" else state["route"]
    if effective_route != "search":
        return state, None

    rag_state = await rag_worker_node(state, rag_tools)
    state = {
        **state,
        "rag_chunks": rag_state.get("rag_chunks", []),
        "retrieval_relevance": rag_state.get("retrieval_relevance", "strong"),
        "retrieval_notice": rag_state.get("retrieval_notice", ""),
    }

    if (
        state.get("retrieval_relevance") == "weak"
        and state.get("retrieval_notice")
        and state.get("request_id")
    ):
        await state["send"]({
            "type": "retrieval_notice",
            "request_id": state["request_id"],
            "message": state["retrieval_notice"],
        })
        search_tool_wait_task = asyncio.create_task(
            state["await_search_tool_request"](
                state["request_id"],
                settings.search_tool_decision_timeout_s,
            )
        )

    return state, search_tool_wait_task


async def run_parallel_research_phase(state: AgentState, rag_tools: list) -> AgentState:
    rag_state, research_state = await asyncio.gather(
        rag_worker_node(state, rag_tools),
        research_worker_node(state),
    )
    return {
        **state,
        "rag_chunks": rag_state.get("rag_chunks", []),
        "retrieval_relevance": rag_state.get("retrieval_relevance", "strong"),
        "retrieval_notice": rag_state.get("retrieval_notice", ""),
        "research_context": research_state.get("research_context", ""),
    }


async def maybe_expand_with_search_tool(
    state: AgentState,
    graph_tools: list,
    search_tool_wait_task: asyncio.Task | None,
) -> AgentState:
    if search_tool_wait_task is None:
        return state

    search_requested = await search_tool_wait_task
    if not search_requested:
        return state

    research_state = await research_worker_node(state)
    expanded_state = {**state, "research_context": research_state.get("research_context", "")}
    return await apply_graph_worker(expanded_state, graph_tools)


def maybe_start_node_enrichment(state: AgentState, node_detail_tools: list) -> None:
    graph_data = state.get("graph_data")
    if not graph_data or not graph_data.get("nodes"):
        return

    rag_search_tool = node_detail_tools[0] if node_detail_tools else None
    if not rag_search_tool:
        return

    asyncio.create_task(
        enrich_all_nodes(
            nodes=graph_data["nodes"],
            edges=graph_data.get("edges", []),
            rag_search_tool=rag_search_tool,
            send=state["send"],
            graph_version=graph_data.get("version"),
        )
    )
