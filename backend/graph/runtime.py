from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from agent.state import GraphData
from graph.artifacts import CanonicalGraphArtifacts
from graph.ids import parent_chunk_id_from_chunk


HIGH_CONFIDENCE = 0.65
QUERY_MATCH_BOOST = 4.0

CONCEPT_BOUNDS = (4, 7)
ARCHITECTURE_BOUNDS = (5, 10)

QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "around",
    "architecture",
    "component",
    "data",
    "deployment",
    "draw",
    "concept",
    "concepts",
    "explain",
    "for",
    "flow",
    "how",
    "in",
    "infrastructure",
    "interaction",
    "interactions",
    "is",
    "it",
    "layout",
    "map",
    "of",
    "production",
    "request",
    "show",
    "system",
    "the",
    "to",
    "what",
    "with",
}

ARCHITECTURE_QUERY_HINTS = (
    "architecture",
    "system design",
    "request flow",
    "service layout",
    "deployment",
    "component interactions",
    "component interaction",
    "serving pipeline",
    "production system",
    "infrastructure",
    "data flow",
)

CROSS_LAYER_HINTS = (
    "map concept",
    "map concepts",
    "architecture and concept",
    "concept and architecture",
    "implements",
    "applies to",
    "connect layers",
)

CONCEPT_TYPE_MAP = {
    "method": "service",
    "component": "service",
    "control": "control",
    "decision": "decision",
    "metric": "decision",
    "risk": "decision",
    "artifact": "datastore",
    "objective": "decision",
}

ARCHITECTURE_TYPE_MAP = {
    "actor": "client",
    "service": "service",
    "datastore": "datastore",
    "pipeline_stage": "service",
    "control": "control",
    "external": "external",
}


def select_canonical_graph(
    *,
    query: str,
    rag_chunks: list[dict[str, Any]],
    artifacts: CanonicalGraphArtifacts,
) -> GraphData | None:
    """Select a bounded canonical subgraph from retrieved parent chunks."""
    layer = choose_layer(query)
    min_nodes, max_nodes = ARCHITECTURE_BOUNDS if layer == "architecture" else CONCEPT_BOUNDS

    chunk_ids = [
        chunk_id
        for chunk_id in (parent_chunk_id_from_chunk(chunk) for chunk in rag_chunks)
        if chunk_id
    ]
    if not chunk_ids:
        return None

    query_tokens = _query_tokens(query)
    if not _has_query_supported_node(chunk_ids, artifacts, query_tokens) and not (
        layer == "architecture"
        and _query_warrants_generic_architecture(query, query_tokens)
    ):
        return None

    seed_scores = _seed_node_scores(chunk_ids, artifacts, layer, query_tokens)
    if not seed_scores:
        return None

    include_cross_layer = _query_warrants_cross_layer(query)
    base_max_nodes = max(min_nodes, max_nodes - 2) if include_cross_layer else max_nodes
    selected_ids = _expand_one_hop(seed_scores, artifacts, layer, base_max_nodes)
    if include_cross_layer:
        selected_ids = _include_cross_layer_nodes(
            selected_ids,
            seed_scores,
            artifacts,
            query_tokens,
            max_nodes,
        )
    high_confidence_nodes = [
        node_id
        for node_id in selected_ids
        if artifacts.nodes[node_id].get("confidence", 0) >= HIGH_CONFIDENCE
    ]
    if len(high_confidence_nodes) < 3 or len(selected_ids) < min_nodes:
        return None

    selected_edges = _select_edges(selected_ids, artifacts, layer, query)
    evidence_backed_edges = [
        edge
        for edge in selected_edges
        if edge.get("confidence", 0) >= HIGH_CONFIDENCE
        and edge.get("supporting_chunk_ids")
        and edge.get("support_spans")
    ]
    if len(evidence_backed_edges) < 2:
        return None

    ordered_node_ids = _topological_node_order(selected_ids, selected_edges)
    id_map = {node_id: _runtime_node_id(node_id) for node_id in ordered_node_ids}
    nodes = [_to_runtime_node(artifacts.nodes[node_id], id_map[node_id]) for node_id in ordered_node_ids]
    edges = [
        _to_runtime_edge(edge, id_map)
        for edge in selected_edges
        if edge["source_id"] in id_map and edge["target_id"] in id_map
    ]

    graph: GraphData = {
        "graph_type": layer,
        "title": _title(query, layer, nodes),
        "nodes": nodes,
        "edges": edges,
        "sequence": _sequence(ordered_node_ids, artifacts, id_map),
    }
    groups = _groups(layer, nodes)
    if groups:
        graph["groups"] = groups
    return graph


def choose_layer(query: str) -> str:
    text = query.lower()
    if any(hint in text for hint in ARCHITECTURE_QUERY_HINTS):
        return "architecture"
    return "concept"


def _seed_node_scores(
    chunk_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
    layer: str,
    query_tokens: set[str],
) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    total = len(chunk_ids)
    for rank, chunk_id in enumerate(chunk_ids):
        link = artifacts.chunk_links.get(chunk_id)
        if not link:
            continue
        rank_weight = max(total - rank, 1) / total
        for node_id in link.get("canonical_node_ids", []):
            node = artifacts.nodes.get(node_id)
            if not node or node["layer"] != layer:
                continue
            query_match = _node_query_match_score(node, query_tokens)
            scores[node_id] += (
                rank_weight
                + float(node.get("confidence", 0))
                + (query_match * QUERY_MATCH_BOOST)
            )
    return dict(scores)


def _expand_one_hop(
    seed_scores: dict[str, float],
    artifacts: CanonicalGraphArtifacts,
    layer: str,
    max_nodes: int,
) -> list[str]:
    scores = dict(seed_scores)
    for edge in artifacts.edges.values():
        if edge.get("layer") != layer:
            continue
        source_id = edge["source_id"]
        target_id = edge["target_id"]
        if source_id in seed_scores and artifacts.nodes.get(target_id, {}).get("layer") == layer:
            scores[target_id] = max(scores.get(target_id, 0), seed_scores[source_id] * 0.55 + edge["confidence"])
        if target_id in seed_scores and artifacts.nodes.get(source_id, {}).get("layer") == layer:
            scores[source_id] = max(scores.get(source_id, 0), seed_scores[target_id] * 0.45 + edge["confidence"])

    return [
        node_id
        for node_id, _ in sorted(
            scores.items(),
            key=lambda item: (-item[1], artifacts.nodes[item[0]]["label"].lower()),
        )[:max_nodes]
    ]


def _include_cross_layer_nodes(
    selected_ids: list[str],
    seed_scores: dict[str, float],
    artifacts: CanonicalGraphArtifacts,
    query_tokens: set[str],
    max_nodes: int,
) -> list[str]:
    selected = list(selected_ids)
    selected_set = set(selected)
    candidate_scores: dict[str, float] = {}

    for edge in artifacts.edges.values():
        if edge.get("layer") != "cross_layer":
            continue
        source_id = edge["source_id"]
        target_id = edge["target_id"]
        source_selected = source_id in selected_set
        target_selected = target_id in selected_set
        if source_selected == target_selected:
            continue

        anchor_id = source_id if source_selected else target_id
        candidate_id = target_id if source_selected else source_id
        candidate = artifacts.nodes.get(candidate_id)
        if not candidate or candidate_id in selected_set:
            continue

        anchor_score = seed_scores.get(anchor_id, 1.0)
        query_match = _node_query_match_score(candidate, query_tokens)
        score = (anchor_score * 0.6) + float(edge.get("confidence", 0)) + query_match
        candidate_scores[candidate_id] = max(candidate_scores.get(candidate_id, 0), score)

    for candidate_id, _ in sorted(
        candidate_scores.items(),
        key=lambda item: (-item[1], artifacts.nodes[item[0]]["label"].lower()),
    ):
        if len(selected) >= max_nodes:
            break
        selected.append(candidate_id)
        selected_set.add(candidate_id)

    return selected


def _select_edges(
    selected_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
    layer: str,
    query: str,
) -> list[dict[str, Any]]:
    selected = set(selected_ids)
    include_cross = _query_warrants_cross_layer(query)
    edges = []
    for edge in artifacts.edges.values():
        edge_layer = edge.get("layer")
        if edge["source_id"] not in selected or edge["target_id"] not in selected:
            continue
        if edge_layer == layer or (include_cross and edge_layer == "cross_layer"):
            edges.append(edge)
    selected_order = {node_id: index for index, node_id in enumerate(selected_ids)}
    edges.sort(
        key=lambda edge: (
            0 if include_cross and edge.get("layer") == "cross_layer" else 1,
            -float(edge.get("confidence", 0)),
            selected_order[edge["source_id"]],
            selected_order[edge["target_id"]],
            edge["relation"],
        )
    )
    return edges[:12]


def _query_warrants_cross_layer(query: str) -> bool:
    text = query.lower()
    return any(hint in text for hint in CROSS_LAYER_HINTS)


def _query_warrants_generic_architecture(query: str, query_tokens: set[str]) -> bool:
    return not query_tokens and choose_layer(query) == "architecture"


def _has_query_supported_node(
    chunk_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
    query_tokens: set[str],
) -> bool:
    if not query_tokens:
        return False
    for chunk_id in chunk_ids:
        link = artifacts.chunk_links.get(chunk_id)
        if not link:
            continue
        for node_id in link.get("canonical_node_ids", []):
            node = artifacts.nodes.get(node_id)
            if node and _node_query_match_score(node, query_tokens) > 0:
                return True
    return False


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 1 and token not in QUERY_STOPWORDS
    }


def _node_query_match_score(
    node: dict[str, Any],
    query_tokens: set[str],
) -> float:
    if not query_tokens:
        return 0.0

    phrases = [node["label"], *node.get("aliases", [])]
    phrase_score = 0.0
    for phrase in phrases:
        phrase_tokens = _phrase_tokens(phrase)
        if not phrase_tokens:
            continue
        if phrase_tokens <= query_tokens:
            phrase_score = max(phrase_score, 1.0 + min(len(phrase_tokens), 4) * 0.35)

    node_tokens = set()
    for phrase in phrases:
        node_tokens.update(_phrase_tokens(phrase))
    overlap_score = min(len(query_tokens & node_tokens) * 0.25, 1.0)
    return phrase_score + overlap_score


def _phrase_tokens(phrase: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", phrase.lower())
        if len(token) > 1 and token not in QUERY_STOPWORDS
    }


def _topological_node_order(selected_ids: list[str], edges: list[dict[str, Any]]) -> list[str]:
    selected = set(selected_ids)
    indegree = {node_id: 0 for node_id in selected_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = edge["source_id"]
        target = edge["target_id"]
        if source in selected and target in selected:
            outgoing[source].append(target)
            indegree[target] += 1

    queue = deque([node_id for node_id in selected_ids if indegree[node_id] == 0])
    ordered = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if len(ordered) != len(selected):
        return selected_ids
    return ordered


def _to_runtime_node(node: dict[str, Any], runtime_id: str) -> dict[str, Any]:
    layer = node["layer"]
    node_type = (
        CONCEPT_TYPE_MAP.get(node["kind"], "service")
        if layer == "concept"
        else ARCHITECTURE_TYPE_MAP.get(node["kind"], "service")
    )
    runtime_node = {
        "id": runtime_id,
        "label": _display_label(node["label"]),
        "type": node_type,
        "technology": _technology_label(layer, node["kind"]),
        "description": node["description"],
        "tier": _tier(layer, node["kind"]),
        "detail": None,
        "layer": layer,
        "canonical_id": node["canonical_id"],
        "confidence": node["confidence"],
        "evidence_chunk_ids": node["source_chunk_ids"],
        "book_refs": _book_refs(node.get("chapter_refs", [])),
    }
    if layer == "architecture" and node["kind"] == "control":
        runtime_node["lane"] = "bottom"
    return runtime_node


def _to_runtime_edge(edge: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    support = edge.get("support_spans") or []
    description = support[0] if support else f"Evidence-backed relation: {edge['relation']}"
    if len(description) > 180:
        description = description[:177].rstrip() + "..."
    return {
        "source": id_map[edge["source_id"]],
        "target": id_map[edge["target_id"]],
        "label": edge["relation"].replace("_", " "),
        "technology": "Book evidence",
        "sync": "sync",
        "description": description,
        "edge_id": edge["edge_id"],
        "relation": edge["relation"],
        "confidence": edge["confidence"],
        "supporting_chunk_ids": edge["supporting_chunk_ids"],
    }


def _sequence(
    ordered_node_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
    id_map: dict[str, str],
) -> list[dict[str, Any]]:
    steps = []
    for index, node_id in enumerate(ordered_node_ids[:6], 1):
        node = artifacts.nodes[node_id]
        steps.append(
            {
                "step": index,
                "nodes": [id_map[node_id]],
                "description": f"Review {node['label']} in the canonical book graph.",
            }
        )
    return steps


def _groups(layer: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if layer != "architecture" or len(nodes) < 5:
        return []
    group_defs = {
        "interface": ("Interface", {"client"}),
        "services": ("Services", {"service", "external"}),
        "storage": ("Storage", {"datastore"}),
        "controls": ("Controls", {"control", "decision"}),
    }
    groups = []
    for group_id, (label, types) in group_defs.items():
        node_ids = [node["id"] for node in nodes if node["type"] in types]
        if node_ids:
            groups.append({"id": f"{group_id}_layer", "label": label, "nodeIds": node_ids})
    return groups


def _runtime_node_id(canonical_id: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", canonical_id.replace(":", "_").lower()).strip("_")


def _display_label(label: str) -> str:
    replacements = {
        "Retrieval-Augmented Generation": "RAG",
        "Parameter-Efficient Fine-Tuning": "PEFT",
        "Low-Rank Adaptation": "LoRA",
        "Supervised Fine-Tuning": "SFT",
    }
    display = replacements.get(label, label)
    words = display.split()
    if len(words) > 3:
        display = " ".join(words[:3])
    if len(display) > 20:
        display = display[:20].rstrip()
    return display


def _technology_label(layer: str, kind: str) -> str:
    if layer == "architecture":
        return {
            "actor": "User",
            "service": "Runtime service",
            "datastore": "Data store",
            "pipeline_stage": "Pipeline",
            "control": "Control",
            "external": "External API",
        }.get(kind, "Architecture")
    return {
        "method": "Book method",
        "component": "Book component",
        "control": "Book control",
        "decision": "Book decision",
        "metric": "Book metric",
        "risk": "Book risk",
        "artifact": "Book artifact",
        "objective": "Book objective",
    }.get(kind, "Book concept")


def _tier(layer: str, kind: str) -> str | None:
    if layer != "architecture":
        return None
    return "public" if kind == "actor" else "private"


def _book_refs(chapter_refs: list[dict[str, Any]]) -> list[str]:
    refs = []
    for ref in chapter_refs[:3]:
        chapter = ref.get("chapter")
        page = ref.get("page_number")
        if chapter is None:
            refs.append(f"p.{page}")
        else:
            refs.append(f"Chapter {chapter}, p.{page}")
    return refs


def _title(query: str, layer: str, nodes: list[dict[str, Any]]) -> str:
    if nodes:
        label = nodes[0]["label"]
        suffix = "Architecture" if layer == "architecture" else "Map"
        return f"{label} {suffix}"
    return "Canonical Graph"
