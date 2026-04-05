# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/tools/graph_worker_tools/generate_graph_tool.py
# Purpose: Tool used by the Graph Worker to emit a structured graph JSON.
#          The worker calls this to formalise its output into the GraphData
#          schema — the tool validates structure and returns the JSON string.
# Language: Python
# Connects to: agent/state.py (GraphData, GraphNode, GraphEdge, GraphStep)
# Inputs:  graph_type, title, nodes, edges, sequence
# Outputs: validated GraphData as JSON string
# ─────────────────────────────────────────────────────────────────────────────

import json

from langchain_core.tools import tool


@tool
def generate_graph(
    graph_type: str,
    title: str,
    nodes: list[dict],
    edges: list[dict],
    sequence: list[dict],
    groups: list[dict] | None = None,
) -> str:
    """
    Emit a structured knowledge graph for rendering in the frontend.

    Args:
        graph_type: "architecture" for system diagrams, "concept" for idea maps
        title:      Short descriptive title e.g. "RAG Inference Pipeline"
        nodes:      List of {id, label, type, technology, description, tier?}
                    type: "client" | "service" | "datastore" | "gateway" | "network" | "external" | "decision"
                    technology: specific tech choice e.g. "Python / FastAPI"
                    description: 1-sentence responsibility summary
                    tier: "public" | "private" (architecture only, optional for concept)
                    lane: "bottom" (optional) — only for cross-cutting observability/monitoring nodes
        edges:      List of {source, target, label, technology, sync, description}
                    label: specific verb phrase e.g. "sends query"
                    technology: transport + format e.g. "HTTPS/JSON", "gRPC/Protobuf"
                    sync: "sync" | "async"
                    description: 1 sentence about what flows here
        sequence:   List of {step, nodes, description} for step-by-step animation.
                    Each step highlights specific node ids. Use [] if no sequence.
        groups:     Optional list of {id, label, nodeIds} semantic groupings.
                    Use for architecture diagrams to cluster related nodes into named layers.

    Returns:
        JSON string matching GraphData schema — sent directly to the frontend.
    """
    _NODE_REQUIRED = ("id", "label", "type", "technology", "description")
    _EDGE_REQUIRED = ("source", "target", "label", "technology", "sync", "description")

    for node in nodes:
        if not all(k in node for k in _NODE_REQUIRED):
            raise ValueError(f"Node missing required fields {_NODE_REQUIRED}: {node}")
        node.setdefault("detail", None)   # filled by Node Detail Workers
        node.setdefault("tier", None)     # optional for concept graphs
        node.setdefault("lane", None)     # "bottom" for cross-cutting observability nodes

    for edge in edges:
        if not all(k in edge for k in _EDGE_REQUIRED):
            raise ValueError(f"Edge missing required fields {_EDGE_REQUIRED}: {edge}")

    graph_data = {
        "graph_type": graph_type,
        "title": title,
        "nodes": nodes,
        "edges": edges,
        "sequence": sequence,
    }
    if groups:
        graph_data["groups"] = groups

    return json.dumps(graph_data, ensure_ascii=False)
