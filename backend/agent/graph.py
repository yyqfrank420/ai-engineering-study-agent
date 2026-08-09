"""LangGraph-backed orchestration for the study and applied-design agents.

The public ``run_agent`` contract is deliberately unchanged: API transports inject
request-scoped tools and an SSE/WebSocket ``send`` callback, then receive the final
``AgentState``. LangGraph owns branching and the bounded design-review loop; provider
streaming and transport backpressure remain inside the existing nodes.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agent.architecture_playbook import build_evidence_bundle
from agent.complexity import (
    resolve_graph_operation,
    resolve_design_query,
)
from agent.deadlines import (
    StageAdmissionDenied,
    WorkflowDeadlineExceeded,
    critic_timeout_seconds,
    design_timeout_seconds,
    patch_timeout_seconds,
    synthesis_timeout_seconds,
)
from agent.nodes.architecture_workers import (
    architect_node,
    challenger_node,
    early_design_frame_node,
)
from agent.nodes.graph_critic import graph_critic_node
from agent.graph_repair_contract import validate_local_repair_admission
from agent.nodes.orchestrator_node import (
    orchestrator_route,
    orchestrator_synthesise,
    quick_synthesise,
)
from agent.pipeline_steps import (
    apply_graph_worker,
    maybe_expand_with_search_tool,
    run_parallel_research_phase,
    run_search_phase,
)
from agent.state import AgentState, GraphOperation
from observability import start_span


NodeResult = Awaitable[AgentState]
AgentNode = Callable[[AgentState], NodeResult]

_GRAPH_STAGE_DEADLINE_KEY = "_graph_stage_deadline_s"
_MAX_GRAPH_REVISIONS = 3
_RETRYABLE_GRAPH_PATCH_FAILURE_CODES = {
    "graph_patch_invalid_preserved_existing_graph",
    "graph_patch_no_effect",
}


def _with_graph_stage_deadline(state: AgentState, timeout_s: float) -> AgentState:
    return {
        **state,
        _GRAPH_STAGE_DEADLINE_KEY: time.monotonic() + timeout_s,
    }  # type: ignore[typeddict-item]


def _without_graph_stage_deadline(state: AgentState) -> AgentState:
    cleaned = dict(state)
    cleaned.pop(_GRAPH_STAGE_DEADLINE_KEY, None)
    return cleaned  # type: ignore[return-value]


def _repair_attempt_summary(revision_count: int) -> str:
    if revision_count <= 0:
        return "before a bounded repair could complete"
    suffix = "attempt" if revision_count == 1 else "attempts"
    return f"after {revision_count} bounded repair {suffix}"


def _restore_approved_graph_state(state: AgentState) -> AgentState:
    return {
        **state,
        "graph_data": copy.deepcopy(state.get("approved_graph_data")),
        "graph_changed": False,
    }


def _failed_graph_operation(
    state: AgentState,
    failure_code: str,
) -> GraphOperation | None:
    operation = state.get("graph_operation")
    if isinstance(operation, dict):
        return {**operation, "status": "failed", "failure_code": failure_code}
    intent = state.get("graph_intent")
    if intent in {"create", "edit"}:
        return {
            "kind": intent,
            "status": "failed",
            "failure_code": failure_code,
        }
    return None


def _should_send_graph_notice(state: AgentState) -> bool:
    return state.get("graph_mode", "auto") != "on"


def _should_preserve_unreviewed_candidate(state: AgentState) -> bool:
    graph = state.get("graph_data")
    review = state.get("graph_review") or {}
    return (
        bool(state.get("graph_changed"))
        and isinstance(graph, dict)
        and graph.get("design_origin") == "applied"
        and isinstance(review, dict)
        and review.get("approved") is False
        and review.get("review_status") == "unavailable"
    )


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

    _ = node_detail_tools

    async def route(state: AgentState) -> AgentState:
        return await orchestrator_route(state)

    async def quick_answer(state: AgentState) -> AgentState:
        return await quick_synthesise(state)

    async def gather_context(state: AgentState) -> AgentState:
        # Restore terse follow-ups to the canonical product intent before any
        # retrieval. Otherwise both the book and web workers search fragments
        # such as "expand this" instead of the system being designed.
        design_query = resolve_design_query(
            state.get("user_message", ""),
            state.get("history"),
            state.get("graph_data"),
        )
        prepared = {**state, "design_query": design_query}
        is_applied = _should_run_applied_design_roles(prepared)
        if prepared.get("research_enabled", False):
            with start_span(
                "agent.parallel_research_phase",
                attributes={"app.research_enabled": True},
            ):
                researched = await run_parallel_research_phase(prepared, rag_tools)
            gathered = {**researched, "search_tool_wait_task": None}
        else:
            with start_span(
                "agent.rag_phase",
                attributes={"app.graph_mode": state.get("graph_mode", "auto")},
            ):
                searched, wait_task = await run_search_phase(prepared, rag_tools)
            gathered = {**searched, "search_tool_wait_task": wait_task}
        bundle = build_evidence_bundle(gathered)
        await state["send"](
            {
                "type": "workflow_progress",
                "phase": "evidence",
                "status": "complete",
                "title": "Evidence frame ready",
                "detail": (
                    "One scenario search is now combined with the standing checks for data, evals, "
                    "security, latency, reliability, and deployment."
                ),
            }
        )
        return {
            **gathered,
            "is_applied_design": is_applied,
            "evidence_bundle": bundle,
        }

    async def architecture_plan(state: AgentState) -> AgentState:
        return await architect_node(state)  # type: ignore[return-value]

    async def challenge_plan(state: AgentState) -> AgentState:
        return await challenger_node(state)  # type: ignore[return-value]

    async def show_early_design_frame(state: AgentState) -> AgentState:
        return await early_design_frame_node(state)  # type: ignore[return-value]

    async def draft_graph(state: AgentState) -> AgentState:
        try:
            timeout_s = design_timeout_seconds(state)
            async with asyncio.timeout(timeout_s):
                drafted = await apply_graph_worker(
                    _with_graph_stage_deadline(state, timeout_s),
                    graph_tools,
                )
                return _without_graph_stage_deadline(drafted)
        except (TimeoutError, StageAdmissionDenied):
            restored = _restore_approved_graph_state(state)
            if not state.get("graph_notice_sent") and _should_send_graph_notice(state):
                await state["send"](
                    {
                        "type": "graph_notice",
                        "message": (
                            "The draft architecture did not meet the structural quality checks, so I "
                            "kept the visual out rather than publishing a misleading graph. The written "
                            "design is still available below."
                        ),
                    }
                )
            operation = _failed_graph_operation(state, "graph_design_timeout")
            return {
                **restored,
                "graph_notice_sent": True,
                **({"graph_operation": operation} if operation else {}),
            }

    async def revise_graph(state: AgentState) -> AgentState:
        revision_count = int(state.get("graph_revision_count", 0)) + 1
        revision_state = {
            **state,
            "graph_revision_count": revision_count,
        }
        try:
            timeout_s = patch_timeout_seconds(revision_state)
        except StageAdmissionDenied:
            restored = _restore_approved_graph_state(state)
            operation = _failed_graph_operation(state, "graph_patch_admission_denied")
            if not state.get("graph_notice_sent") and _should_send_graph_notice(state):
                await state["send"](
                    {
                        "type": "graph_notice",
                        "message": (
                            "I kept the approved diagram unchanged because there was not enough bounded "
                            "time to repair and independently review another candidate."
                        ),
                    }
                )
            return {
                **restored,
                "graph_notice_sent": True,
                "graph_revision_count": revision_count,
                **({"graph_operation": operation} if operation else {}),
            }
        await state["send"](
            {
                "type": "workflow_progress",
                "phase": "revise",
                "status": "retry",
                "title": "Refining the diagram",
                "detail": (
                    f"Repair attempt {revision_count} of {_MAX_GRAPH_REVISIONS}. "
                    "Any valid candidate will then be checked against the real layout."
                ),
            }
        )
        try:
            async with asyncio.timeout(timeout_s):
                revised = await apply_graph_worker(
                    _with_graph_stage_deadline(
                        revision_state,
                        timeout_s,
                    ),
                    graph_tools,
                )
        except TimeoutError:
            restored = _restore_approved_graph_state(state)
            operation = _failed_graph_operation(
                state,
                "graph_patch_timeout_preserved_existing_graph",
            )
            if not state.get("graph_notice_sent") and _should_send_graph_notice(state):
                await state["send"](
                    {
                        "type": "graph_notice",
                        "message": (
                            "I kept the approved diagram unchanged because the bounded repair did not "
                            "finish in time for an independent review."
                        ),
                    }
                )
            return {
                **restored,
                "graph_notice_sent": True,
                "graph_revision_count": revision_count,
                **({"graph_operation": operation} if operation else {}),
            }
        return {
            **_without_graph_stage_deadline(revised),
            "graph_revision_count": revision_count,
        }

    async def expand_context(state: AgentState) -> AgentState:
        expanded = await maybe_expand_with_search_tool(
            state,
            graph_tools,
            state.get("search_tool_wait_task"),
        )
        return {**expanded, "search_tool_wait_task": None}

    async def review_graph(state: AgentState) -> AgentState:
        if not state.get("graph_changed"):
            return await graph_critic_node(state)
        try:
            timeout_s = critic_timeout_seconds(state)
            async with asyncio.timeout(timeout_s):
                reviewed = await graph_critic_node(
                    _with_graph_stage_deadline(state, timeout_s)
                )
                reviewed = _without_graph_stage_deadline(reviewed)
                if (reviewed.get("graph_review") or {}).get("approved"):
                    operation = reviewed.get("graph_operation")
                    if (
                        isinstance(operation, dict)
                        and operation.get("status") == "candidate"
                    ):
                        reviewed = {
                            **reviewed,
                            "graph_operation": {**operation, "status": "applied"},
                        }
                return reviewed
        except (TimeoutError, StageAdmissionDenied):
            return {
                **state,
                "graph_review": {
                    "approved": False,
                    "terminal": True,
                    "review_status": "unavailable",
                    "failure_code": "semantic_review_timeout",
                    "revision_instruction": "Keep the prior approved diagram unchanged.",
                },
            }

    async def reject_graph(state: AgentState) -> AgentState:
        review = state.get("graph_review") or {}
        approved_graph = state.get("approved_graph_data")
        repair_summary = _repair_attempt_summary(
            int(state.get("graph_revision_count", 0))
        )
        preserve_candidate = _should_preserve_unreviewed_candidate(state)
        if not preserve_candidate and not state.get("graph_notice_sent") and _should_send_graph_notice(state):
            operation = state.get("graph_operation")
            failure_code = (
                operation.get("failure_code") if isinstance(operation, dict) else None
            )
            if failure_code == "graph_edit_target_unavailable":
                message = (
                    "I couldn't apply that edit because this thread has no approved applied "
                    "diagram to change. Create or redraw the architecture first."
                )
            elif failure_code == "graph_mode_disabled":
                message = "I kept the diagram unchanged because graph mode is off for this turn."
            else:
                message = (
                    f"I couldn't make this diagram clear enough {repair_summary}, so I kept "
                    + (
                        "the prior approved visual unchanged."
                        if approved_graph
                        else "the visual out."
                    )
                    + " The written architecture is still available below; ask me to redraw it as "
                    "a simpler diagram if you want another pass."
                )
            await state["send"](
                {
                    "type": "graph_notice",
                    "message": message,
                }
            )
        restored = state if preserve_candidate else _restore_approved_graph_state(state)
        operation = state.get("graph_operation")
        return {
            **restored,
            "graph_notice_sent": preserve_candidate or state.get("graph_notice_sent", False),
            "graph_review": review,
            "graph_operation": (
                {
                    **operation,
                    "status": "failed",
                    "failure_code": (
                        review.get("failure_code")
                        or operation.get("failure_code")
                        or "graph_review_rejected"
                    ),
                }
                if isinstance(operation, dict)
                else operation
            ),
        }

    async def synthesise(state: AgentState) -> AgentState:
        try:
            timeout_s = synthesis_timeout_seconds(state)
            async with asyncio.timeout(timeout_s):
                return await orchestrator_synthesise(state)
        except (TimeoutError, StageAdmissionDenied) as exc:
            raise WorkflowDeadlineExceeded(
                "synthesis exceeded its reserved deadline"
            ) from exc

    workflow = StateGraph(AgentState)
    workflow.add_node("route", _traced("agent.orchestrator_route", route))
    workflow.add_node("quick_answer", _traced("agent.quick_synthesise", quick_answer))
    workflow.add_node(
        "gather_context",
        _traced(
            "agent.context_phase",
            gather_context,
            **{
                "app.research_enabled": lambda state: state.get(
                    "research_enabled", False
                )
            },
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
    workflow.add_node(
        "early_design_frame",
        _traced("agent.early_design_frame", show_early_design_frame),
    )
    workflow.add_node(
        "expand_context", _traced("agent.search_tool_wait", expand_context)
    )
    workflow.add_node("review_graph", _traced("agent.graph_review", review_graph))
    workflow.add_node("revise_graph", _traced("agent.graph_revision", revise_graph))
    workflow.add_node("reject_graph", _traced("agent.graph_rejected", reject_graph))
    workflow.add_node(
        "synthesise",
        _traced(
            "agent.synthesis_phase",
            synthesise,
            **{"app.route": lambda state: state.get("route", "")},
        ),
    )

    workflow.add_edge(START, "route")
    workflow.add_conditional_edges(
        "route",
        _route_after_routing,
        {"quick": "quick_answer", "context": "gather_context"},
    )
    workflow.add_edge("quick_answer", END)
    # Resolve an optional weak-book web escalation before the canonical brief
    # is written. The reviewer starts from the original evidence, then checks
    # the primary plan as a clean second pass before graph construction.
    workflow.add_edge("gather_context", "expand_context")
    workflow.add_edge("expand_context", "architect")
    workflow.add_edge("architect", "challenger")
    workflow.add_edge("challenger", "early_design_frame")
    workflow.add_edge("early_design_frame", "draft_graph")
    workflow.add_edge("draft_graph", "review_graph")
    workflow.add_conditional_edges(
        "review_graph",
        _route_after_review,
        {"accept": "synthesise", "revise": "revise_graph", "reject": "reject_graph"},
    )
    workflow.add_conditional_edges(
        "revise_graph",
        _route_after_revision,
        {
            "review": "review_graph",
            "retry": "revise_graph",
            "reject": "reject_graph",
        },
    )
    workflow.add_edge("reject_graph", "synthesise")
    workflow.add_edge("synthesise", END)
    return workflow.compile()


def _route_after_routing(state: AgentState) -> Literal["quick", "context"]:
    return "quick" if state.get("route") == "simple" else "context"


def _should_run_applied_design_roles(state: AgentState) -> bool:
    """Avoid paid design roles when the user explicitly disabled diagrams."""
    graph_intent = state.get("graph_intent") or resolve_graph_operation(
        state.get("user_message", ""),
        state.get("graph_data"),
    )
    return state.get("graph_mode", "auto") != "off" and graph_intent == "create"


def _has_applied_graph(graph_data: dict | None) -> bool:
    return isinstance(graph_data, dict) and graph_data.get("design_origin") == "applied"


def _route_after_review(state: AgentState) -> Literal["accept", "revise", "reject"]:
    operation = state.get("graph_operation")
    graph = state.get("graph_data") or {}
    revision_count = int(state.get("graph_revision_count", 0))
    if isinstance(operation, dict) and operation.get("status") == "failed" and revision_count == 0:
        return "reject"
    if not state.get("graph_changed"):
        if revision_count == 0 or graph.get("design_origin") != "applied":
            return "accept"
    review = state.get("graph_review") or {}
    repair_contract = review.get("repair_contract")
    if isinstance(repair_contract, dict):
        repair_scope = repair_contract.get("repair_scope")
        if repair_scope == "none":
            return "accept" if review.get("approved") else "reject"
        if repair_scope == "global":
            return "reject"
        if repair_scope != "local":
            return "reject"
        try:
            validate_local_repair_admission(repair_contract, graph=graph)
        except ValueError:
            return "reject"
    if review.get("approved"):
        return "accept"
    if (
        not review.get("terminal")
        and revision_count < _MAX_GRAPH_REVISIONS
    ):
        return "revise"
    return "reject"


def _route_after_revision(state: AgentState) -> Literal["review", "retry", "reject"]:
    revision_count = int(state.get("graph_revision_count", 0))
    if not state.get("graph_data") or revision_count <= 0:
        return "reject"
    operation = state.get("graph_operation")
    if isinstance(operation, dict) and operation.get("status") == "failed":
        retryable = (
            operation.get("failure_code") in _RETRYABLE_GRAPH_PATCH_FAILURE_CODES
        )
        if retryable and revision_count < _MAX_GRAPH_REVISIONS:
            return "retry"
        return "reject"
    return "review" if revision_count <= _MAX_GRAPH_REVISIONS else "reject"


async def run_agent(
    state: AgentState,
    rag_tools: list,
    graph_tools: list,
    node_detail_tools: list,
) -> AgentState:
    """Execute the request-scoped LangGraph workflow and return its final state."""
    graph_intent = resolve_graph_operation(
        state.get("user_message", ""),
        state.get("graph_data"),
    )
    graph_operation = state.get("graph_operation")
    if graph_intent == "edit" and state.get("graph_mode") == "off":
        graph_operation = {
            "kind": "edit",
            "status": "failed",
            "failure_code": "graph_mode_disabled",
        }
    elif graph_intent == "edit" and not _has_applied_graph(state.get("graph_data")):
        graph_intent = "create"
        graph_operation = None
    initial_state: AgentState = {
        **state,
        "graph_intent": graph_intent,
        **({"graph_operation": graph_operation} if graph_operation else {}),
        "graph_revision_count": state.get("graph_revision_count", 0),
        "approved_graph_data": copy.deepcopy(
            state.get("approved_graph_data", state.get("graph_data"))
        ),
    }
    workflow = build_agent_workflow(rag_tools, graph_tools, node_detail_tools)
    return await workflow.ainvoke(initial_state, config={"recursion_limit": 24})
