import asyncio
import copy
import json

from agent.architecture_playbook import build_evidence_bundle
from agent.nodes.graph_worker import graph_worker_node
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
            operation = graph_state.get("graph_operation")
            if (
                isinstance(operation, dict)
                and operation.get("failure_code") == "graph_edit_target_unavailable"
            ):
                message = (
                    "I couldn't apply that graph edit because this thread has no approved applied "
                    "diagram to change. Create or redraw the architecture first."
                )
            elif state.get("is_applied_design"):
                message = (
                    "The draft architecture did not meet the structural quality checks, so I kept "
                    "the visual out rather than publishing a misleading graph. The written design "
                    "is still available below."
                )
            else:
                message = (
                    "I found enough related material to explain this, but not enough grounded detail "
                    "from the book to draw a trustworthy graph for this exact question."
                )
            await state["send"](
                {
                    "type": "graph_notice",
                    "message": message,
                }
            )
        return {
            **graph_state,
            "graph_data": existing_graph,
            "graph_changed": False,
            "graph_notice_sent": graph_state.get("graph_notice_sent", False)
            or (existing_graph is None and state.get("route") == "search"),
        }

    if existing_graph is not None and _same_graph_artifact(existing_graph, new_graph):
        aligned_graph = copy.deepcopy(existing_graph)
        if new_graph.get("version") != aligned_graph.get("version"):
            aligned_graph["version"] = new_graph.get("version")
        operation = graph_state.get("graph_operation")
        if (
            isinstance(operation, dict)
            and operation.get("status") == "candidate"
            and operation.get("kind") in {"create", "edit"}
        ):
            operation = {
                **operation,
                "status": "failed",
                "failure_code": "graph_patch_no_effect",
            }
        return {
            **graph_state,
            "graph_data": aligned_graph,
            "graph_changed": False,
            "graph_notice_sent": graph_state.get("graph_notice_sent", False),
            "graph_operation": operation,
        }

    return {
        **graph_state,
        "graph_data": new_graph,
        "graph_changed": True,
        "graph_notice_sent": graph_state.get("graph_notice_sent", False),
    }


def _same_graph_artifact(left: dict, right: dict) -> bool:
    """Ignore release stamps when a failed refinement reuses the approved graph."""
    left_payload = {key: value for key, value in left.items() if key != "version"}
    right_payload = {key: value for key, value in right.items() if key != "version"}
    return json.dumps(left_payload, sort_keys=True) == json.dumps(
        right_payload, sort_keys=True
    )


async def run_search_phase(
    state: AgentState, rag_tools: list
) -> tuple[AgentState, asyncio.Task | None]:
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
        await state["send"](
            {
                "type": "retrieval_notice",
                "request_id": state["request_id"],
                "message": state["retrieval_notice"],
            }
        )
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
        "research_status": research_state.get("research_status", "unavailable"),
    }


async def maybe_expand_with_search_tool(
    state: AgentState,
    _graph_tools: list,
    search_tool_wait_task: asyncio.Task | None,
) -> AgentState:
    if search_tool_wait_task is None:
        return state

    search_requested = await search_tool_wait_task
    if not search_requested:
        return state

    research_state = await research_worker_node(state)
    expanded_state = {
        **state,
        "research_context": research_state.get("research_context", ""),
        "research_status": research_state.get("research_status", "unavailable"),
    }
    # The workflow consumes this evidence before architect/challenger/graph.
    # Keeping one canonical bundle prevents the critic from auditing a stale
    # book-only allowlist after web evidence changes the design.
    return {
        **expanded_state,
        "evidence_bundle": build_evidence_bundle(expanded_state),
    }
