# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/node_detail_worker.py
# Purpose: Phase 3 async node enrichment — for each graph node, runs two RAG
#          searches (by label + by connection context) and generates a concise
#          description with book citations.
#          Runs N workers in parallel (capped at max_graph_nodes) via
#          asyncio.gather. Does NOT block the done event — fires after Phase 2.
# Language: Python
# Connects to: adapters/llm_adapter.py, agent/tools/rag_worker_tools/rag_search_tool.py
#              agent/state.py, config.py
# Inputs:  graph node (id, label, type), edges (for connection context), rag_search_tool
# Outputs: sends node_detail SSE events per node (no state update)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import json
import re
from typing import Any, Callable, Awaitable

from adapters.llm_adapter import stream_response
from agent.state import GraphNode
from config import settings

_SYSTEM = """<role>
You are a study assistant for "AI Engineering" by Chip Huyen.
Your audience is someone new to AI and systems work.
</role>

<task>
For the given concept or component, write one short teaching note for a beginner.
</task>

<format>
- exactly 2 short paragraphs
- paragraph 1: what it is, in plain English, optionally with one simple analogy
- paragraph 2: how it fits into this diagram or flow, and why it matters
</format>

<rules>
- keep it under 95 words total
- no bullet points
- no headings
- no glossary-style lists
- no equations, matrix notation, or formula blocks unless the user explicitly asked for math
- avoid unexplained acronyms; write the full phrase first, then the acronym in parentheses
- cite the most relevant book section inline as (Chapter N, p.X)
- sound like a calm tutor, not lecture notes
</rules>

<weak_evidence_behavior>
- If the book evidence is thin, say that briefly in plain English.
- Stay close to the provided evidence and connected nodes.
- Never invent citations, equations, implementation details, or unsupported claims.
</weak_evidence_behavior>"""


async def enrich_node(
    node: GraphNode,
    edges: list[dict],
    rag_search_tool,
    send: Callable[[dict], Awaitable[None]],
    graph_version: str | None = None,
) -> None:
    """
    Enrich a single graph node with a description and book citations.
    Runs two RAG searches:
      1. Primary: by node label (k=4) — direct concept lookup
      2. Secondary: by label + connected edge labels (k=2) — context-aware

    Parses book citations from the generated description and fires a
    node_detail SSE event with both description and book_refs.
    """
    # ── Primary search by node label ──────────────────────────────────────
    raw1 = rag_search_tool.invoke({"query": node["label"], "k": 4})
    chunks1 = json.loads(raw1) if isinstance(raw1, str) else []

    # ── Secondary search using connection context ──────────────────────────
    connected = [
        e for e in edges
        if e.get("source") == node["id"] or e.get("target") == node["id"]
    ]
    chunks2 = []
    if connected:
        edge_terms = " ".join(e.get("label", "") for e in connected[:3])
        ctx_query = f"{node['label']} {edge_terms}".strip()
        raw2 = rag_search_tool.invoke({"query": ctx_query, "k": 2})
        chunks2 = json.loads(raw2) if isinstance(raw2, str) else []

    # ── Merge and deduplicate by text prefix ──────────────────────────────
    seen: set[str] = set()
    all_chunks: list[dict] = []
    for chunk in chunks1 + chunks2:
        key = chunk.get("text", "")[:60]
        if key not in seen:
            seen.add(key)
            all_chunks.append(chunk)
    all_chunks = all_chunks[:5]

    # ── Format context with citations ──────────────────────────────────────
    context_parts = []
    for c in all_chunks:
        citation = f"Chapter {c.get('chapter', '?')}, p.{c.get('page_number', '?')}"
        context_parts.append(f"[{citation}]\n{c.get('text', '')[:400]}")
    context = "\n\n".join(context_parts) if context_parts else "(no book content found)"

    # ── Build connections summary for the prompt ───────────────────────────
    connections_text = ""
    if connected:
        conn_lines = []
        for e in connected[:5]:
            proto = f" [{e['protocol']}]" if e.get("protocol") else ""
            if e.get("source") == node["id"]:
                conn_lines.append(f"  → {e.get('target', '?')} via '{e.get('label', '?')}'{proto}")
            else:
                conn_lines.append(f"  ← {e.get('source', '?')} via '{e.get('label', '?')}'{proto}")
        connections_text = "\n\nConnections:\n" + "\n".join(conn_lines)

    # Build a richer prompt using the new schema fields
    tech_note = f" [{node.get('technology', '')}]" if node.get('technology') else ""
    tier_note = f" ({node.get('tier', 'unknown')} tier)" if node.get('tier') else ""
    node_desc = node.get("description", "")
    desc_note = f"\nRole: {node_desc}" if node_desc else ""

    messages = [{
        "role": "user",
        "content": (
            f"Explain this concept: **{node['label']}**{tech_note} (type: {node['type']}{tier_note})"
            f"{desc_note}{connections_text}\n\n"
            f"Relevant book content:\n{context}"
        ),
    }]

    description = ""
    async for event_type, content in stream_response(
        model=settings.worker_model,
        system=_SYSTEM,
        messages=messages,
        thinking_budget=None,
        temperature=settings.node_detail_temperature,
        top_p=settings.node_detail_top_p,
        top_k=settings.node_detail_top_k,
    ):
        if event_type == "provider_switch":
            await send({"type": "provider_switch", "provider": content})
        elif event_type == "text":
            description += content

    description = description.strip()
    book_refs = _parse_book_refs(description)

    await send({
        "type": "node_detail",
        "node_id": node["id"],
        "description": description,
        "book_refs": book_refs,
        "graph_version": graph_version,
    })


def _parse_book_refs(text: str) -> list[str]:
    """
    Extract book citation patterns like '(Chapter 3, p.45)' from generated text.
    Returns deduplicated list preserving order.
    """
    pattern = r'\(Chapter\s+\d+[^)]{0,30}\)'
    matches = re.findall(pattern, text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


async def enrich_all_nodes(
    nodes: list[GraphNode],
    edges: list[dict],
    rag_search_tool,
    send: Callable[[dict], Awaitable[None]],
    graph_version: str | None = None,
) -> None:
    """
    Enrich all nodes in parallel, capped at settings.max_graph_nodes workers.
    Called as a fire-and-forget task after Phase 2 (done event already sent).

    Args:
        nodes:           list of GraphNode dicts from the current graph
        edges:           list of GraphEdge dicts — passed to each worker for
                         connection context in the enrichment prompt
        rag_search_tool: bound rag_search tool (vectorstore pre-loaded)
        send:            SSE event callback
    """
    capped_nodes = nodes[:settings.max_graph_nodes]
    tasks = [
        enrich_node(node, edges, rag_search_tool, send, graph_version=graph_version)
        for node in capped_nodes
    ]
    # Run all node workers concurrently — errors in one don't kill others
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for node, result in zip(capped_nodes, results):
        if isinstance(result, Exception):
            # Send an empty detail so the frontend shimmer resolves
            await send({
                "type": "node_detail",
                "node_id": node["id"],
                "description": "",
                "book_refs": [],
                "graph_version": graph_version,
            })
