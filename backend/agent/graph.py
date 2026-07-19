"""LangGraph-backed orchestration for the study and applied-design agents.

The public ``run_agent`` contract is deliberately unchanged: API transports inject
request-scoped tools and an SSE/WebSocket ``send`` callback, then receive the final
``AgentState``. LangGraph owns branching and the bounded design-review loop; provider
streaming and transport backpressure remain inside the existing nodes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agent.architecture_playbook import build_evidence_bundle
from agent.complexity import is_applied_system_design_request
from agent.nodes.architecture_workers import architect_node, challenger_node
from agent.nodes.graph_critic import graph_critic_node
from agent.nodes.orchestrator_node import orchestrator_route, orchestrator_synthesise, quick_synthesise
from agent.pipeline_steps import (
    apply_graph_worker,
    maybe_expand_with_search_tool,
    maybe_start_node_enrichment,
    run_parallel_research_phase,
    run_search_phase,
)
from agent.state import AgentState
from observability import start_span


NodeResult = Awaitable[AgentState]
AgentNode = Callable[[AgentState], NodeResult]


def _traced(name: str, node: AgentNode, **attributes) -> AgentNode:
    async def run(state: AgentState) -> AgentState:
        span_attributes = {
            "app.request_id": state.get("request_id"),
            **{
                key: value(state) if callable(value) else value
                for key, value in attributes.items()
            },
        }
        with start_span(name, attributes=span_attributes):
            return await node(state)

    return run


def build_agent_workflow(
    rag_tools: list,
    graph_tools: list,
    node_detail_tools: list,
):
    """Build one request-scoped workflow with its bound tools.

    Tool callables and network callbacks are intentionally closure-bound instead of
    checkpointed state. This keeps the graph state serialisable enough to migrate to
    a durable checkpointer later without ever attempting to persist live I/O handles.
    """

    async def route(state: AgentState) -> AgentState:
        return await orchestrator_route(state)

    async def quick_answer(state: AgentState) -> AgentState:
        return await quick_synthesise(state)

    async def gather_context(state: AgentState) -> AgentState:
        if state.get("research_enabled", False):
            with start_span(
                "agent.parallel_research_phase",
                attributes={"app.research_enabled": True},
            ):
                researched = await run_parallel_research_phase(state, rag_tools)
            gathered = {**researched, "search_tool_wait_task": None}
        else:
            with start_span(
                "agent.rag_phase",
                attributes={"app.graph_mode": state.get("graph_mode", "auto")},
            ):
                searched, wait_task = await run_search_phase(state, rag_tools)
            gathered = {**searched, "search_tool_wait_task": wait_task}
        is_applied = _should_run_applied_design_roles(gathered)
        bundle = build_evidence_bundle(gathered)
        await state["send"]({
            "type": "workflow_progress",
            "phase": "evidence",
            "status": "complete",
            "title": "Evidence frame ready",
            "detail": (
                "One scenario search is now combined with the standing checks for data, evals, "
                "security, latency, reliability, and deployment."
            ),
        })
        return {
            **gathered,
            "is_applied_design": is_applied,
            "evidence_bundle": bundle,
        }

    async def architecture_plan(state: AgentState) -> AgentState:
        return await architect_node(state)  # type: ignore[return-value]

    async def challenge_plan(state: AgentState) -> AgentState:
        return await challenger_node(state)  # type: ignore[return-value]

    async def draft_graph(state: AgentState) -> AgentState:
        return await apply_graph_worker(state, graph_tools)

    async def expand_context(state: AgentState) -> AgentState:
        expanded = await maybe_expand_with_search_tool(
            state,
            graph_tools,
            state.get("search_tool_wait_task"),
        )
        return {**expanded, "search_tool_wait_task": None}

    async def review_graph(state: AgentState) -> AgentState:
        return await graph_critic_node(state)

    async def reject_graph(state: AgentState) -> AgentState:
        review = state.get("graph_review") or {}
        await state["send"]({
            "type": "graph_notice",
            "message": (
                "The draft diagram did not pass the architecture and rendered-clarity review, "
                "so I left it out instead of showing a generic or misleading graph."
            ),
        })
        return {
            **state,
            "graph_data": None,
            "graph_changed": False,
            "graph_notice_sent": True,
            "graph_review": review,
        }

    async def synthesise(state: AgentState) -> AgentState:
        return await orchestrator_synthesise(state)

    async def enrich(state: AgentState) -> AgentState:
        await maybe_start_node_enrichment(state, node_detail_tools)
        return state

    workflow = StateGraph(AgentState)
    workflow.add_node("route", _traced("agent.orchestrator_route", route))
    workflow.add_node("quick_answer", _traced("agent.quick_synthesise", quick_answer))
    workflow.add_node(
        "gather_context",
        _traced(
            "agent.context_phase",
            gather_context,
            **{"app.research_enabled": lambda state: state.get("research_enabled", False)},
        ),
    )
    workflow.add_node(
        "draft_graph",
        _traced(
            "agent.graph_phase",
            draft_graph,
            **{"app.graph_mode": lambda state: state.get("graph_mode", "auto")},
        ),
    )
    workflow.add_node("architect", _traced("agent.architect", architecture_plan))
    workflow.add_node("challenger", _traced("agent.challenger", challenge_plan))
    workflow.add_node("expand_context", _traced("agent.search_tool_wait", expand_context))
    workflow.add_node("review_graph", _traced("agent.graph_review", review_graph))
    workflow.add_node("reject_graph", _traced("agent.graph_rejected", reject_graph))
    workflow.add_node(
        "synthesise",
        _traced(
            "agent.synthesis_phase",
            synthesise,
            **{"app.route": lambda state: state.get("route", "")},
        ),
    )
    workflow.add_node("enrich", _traced("agent.node_enrichment_phase", enrich))

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges(
        "route",
        _route_after_routing,
        {"quick": "quick_answer", "context": "gather_context"},
    )
    workflow.add_edge("quick_answer", END)
    # The two roles see the same evidence and run independently. LangGraph waits
    # for both branches before the integrator/graph worker starts.
    workflow.add_edge("gather_context", "architect")
    workflow.add_edge("gather_context", "challenger")
    workflow.add_edge("architect", "draft_graph")
    workflow.add_edge("challenger", "draft_graph")
    workflow.add_edge("draft_graph", "expand_context")
    workflow.add_edge("expand_context", "review_graph")
    workflow.add_conditional_edges(
        "review_graph",
        _route_after_review,
        {"accept": "synthesise", "reject": "reject_graph"},
    )
    workflow.add_edge("reject_graph", "synthesise")
    workflow.add_edge("synthesise", "enrich")
    workflow.add_edge("enrich", END)
    return workflow.compile()


def _route_after_routing(state: AgentState) -> Literal["quick", "context"]:
    return "quick" if state.get("route") == "simple" else "context"


def _should_run_applied_design_roles(state: AgentState) -> bool:
    """Avoid paid design roles when the user explicitly disabled diagrams."""
    return (
        state.get("graph_mode", "auto") != "off"
        and is_applied_system_design_request(state.get("user_message", ""))
    )


def _route_after_review(state: AgentState) -> Literal["accept", "reject"]:
    graph = state.get("graph_data") or {}
    if not state.get("graph_changed") or graph.get("design_origin") != "applied":
        return "accept"
    review = state.get("graph_review") or {}
    if review.get("approved"):
        return "accept"
    return "reject"


async def run_agent(
    state: AgentState,
    rag_tools: list,
    graph_tools: list,
    node_detail_tools: list,
) -> AgentState:
    """Execute the request-scoped LangGraph workflow and return its final state."""
    initial_state: AgentState = {
        **state,
        "graph_revision_count": state.get("graph_revision_count", 0),
    }
    workflow = build_agent_workflow(rag_tools, graph_tools, node_detail_tools)
    return await workflow.ainvoke(initial_state, config={"recursion_limit": 20})
