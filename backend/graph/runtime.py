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
    if _is_customer_support_agent_architecture_query(query) and _has_customer_support_pattern_support(
        chunk_ids,
        artifacts,
    ):
        return _customer_support_agent_architecture(query, chunk_ids, artifacts)

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
    if _is_customer_support_agent_architecture_query(text):
        return "architecture"
    if any(hint in text for hint in ARCHITECTURE_QUERY_HINTS):
        return "architecture"
    return "concept"


def _is_customer_support_agent_architecture_query(query: str) -> bool:
    text = query.lower()
    customer_support = (
        "customer support" in text
        or ("support" in text and ("chatbot" in text or "bot" in text or "ticket" in text))
    )
    agent_architecture = (
        "multi-agent" in text
        or "sub-agent" in text
        or "subagent" in text
        or "all agents" in text
        or ("agent" in text and any(hint in text for hint in ARCHITECTURE_QUERY_HINTS))
        or ("agent" in text and any(role in text for role in ("billing", "returns", "escalation", "faq")))
    )
    return customer_support and agent_architecture


def _has_customer_support_pattern_support(
    chunk_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
) -> bool:
    supported_ids = {
        node_id
        for chunk_id in chunk_ids
        for node_id in artifacts.chunk_links.get(chunk_id, {}).get("canonical_node_ids", [])
    }
    agent_pattern = {
        "architecture:application",
        "architecture:tool_service",
        "concept:agent",
    }
    orchestrator_pattern = {
        "architecture:application",
        "architecture:orchestrator",
        "architecture:tool_service",
    }
    return agent_pattern <= supported_ids or orchestrator_pattern <= supported_ids


def _customer_support_agent_architecture(
    query: str,
    chunk_ids: list[str],
    artifacts: CanonicalGraphArtifacts,
) -> GraphData:
    evidence = _support_bundle(
        artifacts,
        [
            "architecture:user",
            "architecture:application",
            "architecture:orchestrator",
            "architecture:tool_service",
            "architecture:retriever_service",
            "architecture:document_store",
            "architecture:model_server",
            "architecture:llm_provider",
            "architecture:evaluation_pipeline",
            "concept:agent",
            "concept:planning",
            "concept:tool_use",
        ],
        chunk_ids,
    )
    chunk_evidence = evidence["chunk_ids"]
    refs = evidence["book_refs"]
    confidence = evidence["confidence"]

    def node(
        node_id: str,
        label: str,
        node_type: str,
        technology: str,
        description: str,
        tier: str | None,
        grounded_id: str,
    ) -> dict[str, Any]:
        return {
            "id": node_id,
            "label": label,
            "type": node_type,
            "technology": technology,
            "description": description,
            "tier": tier,
            "detail": None,
            "layer": "architecture",
            "canonical_id": f"applied:customer_support:{node_id}",
            "grounded_canonical_id": grounded_id,
            "confidence": confidence,
            "evidence_chunk_ids": chunk_evidence,
            "book_refs": refs,
        }

    nodes = [
        node("customer", "Customer", "client", "Web / mobile chat", "Starts the support conversation.", "public", "architecture:user"),
        node("support_app", "Support App", "service", "Chat UI / API", "Accepts messages and streams responses back to the customer.", "public", "architecture:application"),
        node("orchestrator", "Orchestrator", "service", "Coordinator agent", "Classifies intent, plans the workflow, and delegates to specialist agents.", "private", "architecture:orchestrator"),
        node("intent_router", "Intent Router", "decision", "Intent classifier", "Separates FAQ, billing, returns, escalation, and irrelevant requests.", "private", "concept:agent"),
        node("faq_agent", "FAQ Agent", "service", "RAG agent", "Answers policy and FAQ questions from grounded support documents.", "private", "architecture:retriever_service"),
        node("billing_agent", "Billing Agent", "service", "Tool-using agent", "Handles invoices, payments, refunds, and account-balance questions.", "private", "concept:tool_use"),
        node("returns_agent", "Returns Agent", "service", "Tool-using agent", "Checks order status, eligibility windows, labels, and return workflows.", "private", "concept:tool_use"),
        node("escalation_agent", "Escalation Agent", "service", "Handoff agent", "Creates tickets or routes high-risk cases to human support.", "private", "concept:planning"),
        node("model_runtime", "Model Runtime", "external", "LLM provider", "Provides reasoning and response generation for the coordinator and sub-agents.", "private", "architecture:model_server"),
        node("policy_kb", "Policy KB", "datastore", "Document store", "Stores policies, FAQs, macros, and previous resolved-ticket examples.", "private", "architecture:document_store"),
        node("tool_service", "Tool Service", "external", "CRM / order APIs", "Mediates access to billing, order, CRM, and ticketing systems.", "private", "architecture:tool_service"),
        node("human_support", "Human Support", "external", "Ticket queue", "Reviews escalations, edge cases, and actions requiring approval.", "private", "architecture:user"),
    ]

    def edge(
        source: str,
        target: str,
        label: str,
        description: str,
        relation: str,
        sync: str = "sync",
    ) -> dict[str, Any]:
        return {
            "source": source,
            "target": target,
            "label": label,
            "technology": "HTTPS/JSON",
            "sync": sync,
            "description": description,
            "edge_id": f"applied:customer_support:{source}__{relation}__{target}",
            "relation": relation,
            "confidence": confidence,
            "supporting_chunk_ids": chunk_evidence,
        }

    edges = [
        edge("customer", "support_app", "sends message", "The customer message enters the support application.", "sends_to"),
        edge("support_app", "orchestrator", "calls", "The app asks the coordinator agent to handle the case.", "calls"),
        edge("orchestrator", "intent_router", "classifies intent", "The coordinator classifies the case before delegation.", "routes_to"),
        edge("orchestrator", "model_runtime", "uses model", "The coordinator and specialist agents use the model runtime for reasoning.", "calls"),
        edge("intent_router", "faq_agent", "routes FAQ", "Policy and how-to questions go to the FAQ/RAG agent.", "routes_to"),
        edge("intent_router", "billing_agent", "routes billing", "Invoice, payment, refund, and balance issues go to billing.", "routes_to"),
        edge("intent_router", "returns_agent", "routes returns", "Order and return requests go to the returns agent.", "routes_to"),
        edge("intent_router", "escalation_agent", "routes risk", "Sensitive, failed, or complex cases go to escalation.", "routes_to"),
        edge("faq_agent", "policy_kb", "retrieves docs", "The FAQ agent grounds answers in support documents.", "reads_from"),
        edge("billing_agent", "tool_service", "calls tools", "The billing agent reads or updates billing systems through tools.", "calls"),
        edge("returns_agent", "tool_service", "calls tools", "The returns agent checks order systems and creates return actions through tools.", "calls"),
        edge("escalation_agent", "tool_service", "opens ticket", "The escalation agent writes ticket or CRM records.", "calls"),
        edge("escalation_agent", "human_support", "hands off", "Cases requiring judgment or approval move to human support.", "routes_to", sync="async"),
    ]

    return {
        "graph_type": "architecture",
        "title": "Customer Support Multi-Agent Architecture",
        "nodes": nodes,
        "edges": edges,
        "sequence": [
            {"step": 1, "nodes": ["customer", "support_app"], "description": "Customer message enters the support app."},
            {"step": 2, "nodes": ["orchestrator", "intent_router"], "description": "Coordinator classifies intent and chooses a specialist agent."},
            {"step": 3, "nodes": ["faq_agent", "billing_agent", "returns_agent", "escalation_agent"], "description": "The selected sub-agent plans and handles the case."},
            {"step": 4, "nodes": ["policy_kb", "tool_service", "model_runtime"], "description": "Agents retrieve knowledge, call business tools, and use model reasoning."},
            {"step": 5, "nodes": ["human_support"], "description": "Risky or unresolved cases are escalated to human support."},
        ],
        "groups": [
            {"id": "entry_layer", "label": "Customer Entry", "nodeIds": ["customer", "support_app"]},
            {"id": "agent_layer", "label": "Agent Layer", "nodeIds": ["orchestrator", "intent_router", "faq_agent", "billing_agent", "returns_agent", "escalation_agent"]},
            {"id": "tool_data_layer", "label": "Tools and Data", "nodeIds": ["policy_kb", "tool_service", "model_runtime"]},
            {"id": "human_layer", "label": "Human Review", "nodeIds": ["human_support"]},
        ],
    }


def _support_bundle(
    artifacts: CanonicalGraphArtifacts,
    canonical_ids: list[str],
    chunk_ids: list[str],
) -> dict[str, Any]:
    allowed_chunks = set(chunk_ids)
    supported_nodes = [artifacts.nodes[node_id] for node_id in canonical_ids if node_id in artifacts.nodes]
    chunk_evidence = sorted(
        {
            chunk_id
            for node in supported_nodes
            for chunk_id in node.get("source_chunk_ids", [])
            if not allowed_chunks or chunk_id in allowed_chunks
        },
        key=_chunk_sort_key,
    )
    if not chunk_evidence:
        chunk_evidence = sorted(allowed_chunks, key=_chunk_sort_key)

    refs: list[str] = []
    for node in supported_nodes:
        refs.extend(_book_refs(node.get("chapter_refs", [])))

    confidences = [float(node.get("confidence", 0)) for node in supported_nodes]
    return {
        "chunk_ids": chunk_evidence[:6],
        "book_refs": _dedupe_text(refs)[:4],
        "confidence": max(HIGH_CONFIDENCE, min(confidences) if confidences else HIGH_CONFIDENCE),
    }


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


def _chunk_sort_key(chunk_id: str) -> tuple[int, int, str]:
    match = re.search(r":p(\d+):pc(\d+)$", chunk_id)
    if not match:
        return (10**9, 10**9, chunk_id)
    return (int(match.group(1)), int(match.group(2)), chunk_id)


def _dedupe_text(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _title(query: str, layer: str, nodes: list[dict[str, Any]]) -> str:
    if nodes:
        label = nodes[0]["label"]
        suffix = "Architecture" if layer == "architecture" else "Map"
        return f"{label} {suffix}"
    return "Canonical Graph"
