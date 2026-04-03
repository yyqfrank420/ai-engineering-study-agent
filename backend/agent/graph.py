# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/graph.py
# Purpose: Agent pipeline runner. Wires the 4-phase pipeline:
#          Phase 0:  orchestrator routes (memory vs search)
#          Phase 1a: rag_worker + research_worker run in parallel
#          Phase 1b: graph_worker runs after 1a (uses both RAG + research context)
#          Phase 2:  orchestrator synthesises + streams response
#          Phase 3:  node detail workers run async after done (fire-and-forget)
#
#          graph_mode controls whether graph_worker runs:
#            "auto" — existing routing logic decides
#            "on"   — always run graph_worker (treats route as "search")
#            "off"  — never run graph_worker
#
#          research_enabled controls whether research_worker runs in Phase 1a.
# Language: Python
# Connects to: agent/nodes/*, agent/state.py, config.py
# Inputs:  AgentState (injected at invocation time)
# Outputs: final AgentState after all phases complete
# ─────────────────────────────────────────────────────────────────────────────

from agent.nodes.orchestrator_node import orchestrator_route, orchestrator_synthesise, quick_synthesise
from agent.pipeline_steps import (
    apply_graph_worker,
    maybe_expand_with_search_tool,
    maybe_start_node_enrichment,
    run_parallel_research_phase,
    run_search_phase,
)
from agent.state import AgentState


async def run_agent(
    state: AgentState,
    rag_tools: list,
    graph_tools: list,
    node_detail_tools: list,
) -> AgentState:
    """
    Run the full 4-phase agent pipeline.

    The pipeline is implemented directly with asyncio instead of a graph runtime.
    That keeps the data flow explicit and easy to trace.

    Phase 0  — Route
    Phase 1a — Parallel: rag_worker + research_worker (if enabled)
    Phase 1b — Serial:   graph_worker (uses research_context from 1a)
    Phase 2  — Synthesise + stream response
    Phase 3  — Async node enrichment (fire-and-forget, doesn't block done)

    Args:
        state:              Initial AgentState with thread identifier,
                            user_message, history, and send callback injected
        rag_tools:          [rag_search_tool, get_section_tool]
        graph_tools:        [generate_graph_tool, get_section_tool]
        node_detail_tools:  [get_section_tool]
    """

    # ── Phase 0: Route ────────────────────────────────────────────────────────
    state = await orchestrator_route(state)

    # Simple factual questions skip RAG + graph entirely — answered by Haiku directly
    if state["route"] == "simple":
        return await quick_synthesise(state)

    research_enabled = state.get("research_enabled", False)

    # ── Phase 1a: RAG + research in parallel ──────────────────────────────────
    if research_enabled:
        state = await run_parallel_research_phase(state, rag_tools)
        search_tool_wait_task = None
    else:
        state, search_tool_wait_task = await run_search_phase(state, rag_tools)

    # ── Phase 1b: Graph worker ────────────────────────────────────────────────
    state = await apply_graph_worker(state, graph_tools)

    # If the user explicitly asked for broader context before synthesis,
    # rerun the graph worker so the diagram and final answer reflect the same evidence bundle.
    state = await maybe_expand_with_search_tool(state, graph_tools, search_tool_wait_task)

    # ── Phase 2: Synthesise + stream ──────────────────────────────────────────
    state = await orchestrator_synthesise(state)

    # ── Phase 3: Async node enrichment (non-blocking) ─────────────────────────
    maybe_start_node_enrichment(state, node_detail_tools)

    return state
