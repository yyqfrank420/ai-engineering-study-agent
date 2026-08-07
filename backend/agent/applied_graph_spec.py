from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any

from agent.state import GraphData
from config import settings


_NODE_TYPES = (
    "client",
    "service",
    "datastore",
    "queue",
    "gateway",
    "network",
    "external",
    "control",
    "decision",
)
_TIERS = ("public", "private")
_LANES = ("main", "bottom")
_FLOWS = ("runtime", "control", "feedback", "deployment")
_SYNC_MODES = ("sync", "async")
_GROUP_KINDS = ("runtime", "data", "operations", "delivery", "external")
_ROOT_PARENT_INDEX = -1
GRAPH_EDGE_LABEL_CHARS = 100

logger = logging.getLogger(__name__)

_ERROR_RULES = frozenset({
    "blank_required",
    "container_type",
    "duplicate",
    "invalid_enum",
    "invalid_index",
    "json_decode",
    "key_set",
    "provider_finish",
    "safety_limit",
    "topology",
    "value_type",
})


@dataclass(frozen=True)
class AppliedGraphSpec:
    depth: str
    safety_max_nodes: int
    safety_max_edges: int
    title_chars: int = 100
    node_label_chars: int = 60
    group_label_chars: int = 80
    responsibility_chars: int = 220
    edge_label_chars: int = GRAPH_EDGE_LABEL_CHARS
    assumption_chars: int = 240
    query_chars: int = 8000


class AppliedGraphSpecError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        node_count: int | None = None,
        edge_count: int | None = None,
        path: str | None = None,
        rule: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.node_count = node_count
        self.edge_count = edge_count
        safe_path_chars = frozenset(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$.[ ]"
        )
        self.path = (
            path[:96]
            if isinstance(path, str)
            and path
            and all(char in safe_path_chars for char in path[:96])
            else None
        )
        self.rule = rule if rule in _ERROR_RULES else None


def applied_graph_spec(depth: str) -> AppliedGraphSpec:
    return AppliedGraphSpec(
        depth=depth if depth in {"low", "prototype", "production"} else "production",
        safety_max_nodes=settings.graph_safety_max_nodes,
        safety_max_edges=settings.graph_safety_max_edges,
    )


def applied_graph_topology_schema(_spec: AppliedGraphSpec) -> dict[str, Any]:
    node_record = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "label",
            "type",
            "tier",
            "lane",
            "responsibility",
            "group",
            "group_kind",
            "parent_index",
            "parent_label",
            "parent_flow",
            "parent_sync",
            "sequence_step",
        ],
        "properties": {
            "label": {"type": "string"},
            "type": {"type": "string", "enum": list(_NODE_TYPES)},
            "tier": {"type": "string", "enum": list(_TIERS)},
            "lane": {"type": "string", "enum": list(_LANES)},
            "responsibility": {"type": "string"},
            "group": {"type": "string"},
            "group_kind": {"type": "string", "enum": list(_GROUP_KINDS)},
            "parent_index": {"type": "integer"},
            "parent_label": {"type": "string"},
            "parent_flow": {"type": "string", "enum": list(_FLOWS)},
            "parent_sync": {"type": "string", "enum": list(_SYNC_MODES)},
            "sequence_step": {"type": "integer"},
        },
    }
    cross_link_record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_index", "target_index", "label", "flow", "sync"],
        "properties": {
            "source_index": {"type": "integer"},
            "target_index": {"type": "integer"},
            "label": {"type": "string"},
            "flow": {"type": "string", "enum": list(_FLOWS)},
            "sync": {"type": "string", "enum": list(_SYNC_MODES)},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "nodes", "cross_links"],
        "properties": {
            "title": {"type": "string"},
            "nodes": {"type": "array", "items": node_record},
            "cross_links": {"type": "array", "items": cross_link_record},
        },
    }


def _bounded_input(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def applied_graph_topology_prompt(
    *,
    query: str,
    architect_plan: Any,
    challenger_review: Any,
    commitments: str,
    spec: AppliedGraphSpec,
) -> str:
    design_input = {
        "request": _bounded_input(query, spec.query_chars),
        "depth": spec.depth,
        "architect_plan": architect_plan,
        "challenger_review": challenger_review,
        "diagram_commitments": commitments,
    }
    return (
        "Build the complete architecture topology from the supplied design input. Include every "
        "material responsibility, ownership boundary, runtime branch, control path, data store, "
        "delivery path, and failure outcome needed by this specific system. Choose the number of "
        "nodes, groups, and cross-links from the design. Never merge distinct owners, trust "
        "boundaries, authoritative stores, decisions, or failure outcomes to make the diagram "
        "smaller. Every node belongs to one authored responsibility group. Use the same group label "
        "and kind on nodes that share a visual zone. Order nodes in a stable visual reading order. "
        "The first node is the root and uses parent_index -1. Every later node uses the zero-based "
        "index of one non-self parent. Parent links must form one rooted acyclic topology. Set "
        "sequence_step to a positive runtime order for nodes on the primary observable flow and 0 "
        "for supporting nodes. Parallel nodes may share a step. Cross-links use zero-based source "
        "and target indexes. Include all material non-tree connections. Every approval decision "
        "needs distinct approved and rejected routes. Rejection is a no-effect outcome. A failure "
        "after an effect uses a separate bounded compensation route through the normal controls. "
        "Retry exhaustion, success, COMMITTED, NOT_FOUND, and STILL_UNKNOWN remain distinct outcomes "
        "when they apply. Canary, promotion, and rollback remain distinct delivery paths when they "
        "apply. Edge labels state the visible action or control contract. External mutations show "
        "validation, approval, execution, authoritative state, and reconciliation as distinct "
        "responsibilities when those boundaries apply. Keep the title at most 100 characters, node "
        "labels at most 60 characters, group labels at most 80 characters, responsibilities at most "
        f"220 characters, and edge labels at most {spec.edge_label_chars} characters. Return only "
        "the schema-constrained object.\n"
        + json.dumps(design_input, ensure_ascii=False, separators=(",", ":"))
    )


def _required_text(value: Any, limit: int, *, path: str) -> str:
    if not isinstance(value, str):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="blank_required"
        )
    if len(normalized) > limit:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="safety_limit"
        )
    return normalized


def _canonical_token(value: Any, allowed: tuple[str, ...], *, path: str) -> str:
    if not isinstance(value, str):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    canonical = {token.lower(): token for token in allowed}.get(value.strip().lower())
    if canonical is None:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="invalid_enum"
        )
    return canonical


def _required_index(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    return value


def _raise_topology(path: str) -> None:
    raise AppliedGraphSpecError(
        "graph_design_topology_invalid", path=path, rule="topology"
    )


def validate_applied_graph_topology(
    payload: Any,
    spec: AppliedGraphSpec,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "title",
        "nodes",
        "cross_links",
    }:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="$", rule="key_set"
        )

    title = _required_text(payload["title"], spec.title_chars, path="title")
    raw_nodes = payload["nodes"]
    raw_cross_links = payload["cross_links"]
    if not isinstance(raw_nodes, list):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="nodes", rule="container_type"
        )
    if not raw_nodes:
        raise AppliedGraphSpecError(
            "graph_design_topology_invalid", node_count=0, path="nodes", rule="topology"
        )
    if len(raw_nodes) > spec.safety_max_nodes:
        raise AppliedGraphSpecError(
            "graph_design_node_safety_limit",
            node_count=len(raw_nodes),
            path="nodes",
            rule="safety_limit",
        )
    if not isinstance(raw_cross_links, list):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="cross_links", rule="container_type"
        )
    if len(raw_nodes) - 1 + len(raw_cross_links) > spec.safety_max_edges:
        raise AppliedGraphSpecError(
            "graph_design_edge_safety_limit",
            node_count=len(raw_nodes),
            edge_count=len(raw_nodes) - 1 + len(raw_cross_links),
            path="cross_links",
            rule="safety_limit",
        )

    node_keys = {
        "label",
        "type",
        "tier",
        "lane",
        "responsibility",
        "group",
        "group_kind",
        "parent_index",
        "parent_label",
        "parent_flow",
        "parent_sync",
        "sequence_step",
    }
    nodes: list[dict[str, Any]] = []
    parents: list[int] = []
    parent_metadata: list[dict[str, str]] = []
    for index, raw_node in enumerate(raw_nodes):
        path = f"nodes[{index}]"
        if not isinstance(raw_node, dict) or set(raw_node) != node_keys:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="key_set"
            )
        parent_index = _required_index(
            raw_node["parent_index"], path=f"{path}.parent_index"
        )
        sequence_step = _required_index(
            raw_node["sequence_step"], path=f"{path}.sequence_step"
        )
        if sequence_step < 0:
            _raise_topology(f"{path}.sequence_step")
        if index == 0:
            if parent_index != _ROOT_PARENT_INDEX:
                _raise_topology(path)
        elif parent_index < 0 or parent_index >= len(raw_nodes) or parent_index == index:
            _raise_topology(f"{path}.parent_index")

        node_type = _canonical_token(raw_node["type"], _NODE_TYPES, path=f"{path}.type")
        nodes.append({
            "id": f"n{index + 1}",
            "label": _required_text(
                raw_node["label"], spec.node_label_chars, path=f"{path}.label"
            ),
            "type": node_type,
            "tier": _canonical_token(raw_node["tier"], _TIERS, path=f"{path}.tier"),
            "lane": _canonical_token(raw_node["lane"], _LANES, path=f"{path}.lane"),
            "responsibility": _required_text(
                raw_node["responsibility"],
                spec.responsibility_chars,
                path=f"{path}.responsibility",
            ),
            "group": _required_text(
                raw_node["group"], spec.group_label_chars, path=f"{path}.group"
            ),
            "group_kind": _canonical_token(
                raw_node["group_kind"], _GROUP_KINDS, path=f"{path}.group_kind"
            ),
            "sequence_step": sequence_step,
        })
        parents.append(parent_index)
        parent_metadata.append({
            "label": (
                ""
                if index == 0
                else _required_text(
                    raw_node["parent_label"],
                    spec.edge_label_chars,
                    path=f"{path}.parent_label",
                )
            ),
            "flow": _canonical_token(
                raw_node["parent_flow"], _FLOWS, path=f"{path}.parent_flow"
            ),
            "sync": _canonical_token(
                raw_node["parent_sync"], _SYNC_MODES, path=f"{path}.parent_sync"
            ),
        })
        if index == 0 and not isinstance(raw_node["parent_label"], str):
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid",
                path=f"{path}.parent_label",
                rule="value_type",
            )

    for index in range(1, len(nodes)):
        seen: set[int] = set()
        current = index
        while current != 0:
            if current in seen:
                _raise_topology(f"nodes[{index}].parent_index")
            seen.add(current)
            current = parents[current]

    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index in range(1, len(nodes)):
        metadata = parent_metadata[index]
        edge = {
            "source": f"n{parents[index] + 1}",
            "target": f"n{index + 1}",
            "label": metadata["label"],
            "flow": metadata["flow"],
            "sync": metadata["sync"],
        }
        edges.append(edge)
        seen_edges.add((edge["source"], edge["target"], edge["label"].lower()))

    edge_keys = {"source_index", "target_index", "label", "flow", "sync"}
    for index, raw_edge in enumerate(raw_cross_links):
        path = f"cross_links[{index}]"
        if not isinstance(raw_edge, dict) or set(raw_edge) != edge_keys:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="key_set"
            )
        source_index = _required_index(
            raw_edge["source_index"], path=f"{path}.source_index"
        )
        target_index = _required_index(
            raw_edge["target_index"], path=f"{path}.target_index"
        )
        if (
            source_index < 0
            or source_index >= len(nodes)
            or target_index < 0
            or target_index >= len(nodes)
            or source_index == target_index
        ):
            _raise_topology(path)
        edge = {
            "source": f"n{source_index + 1}",
            "target": f"n{target_index + 1}",
            "label": _required_text(
                raw_edge["label"], spec.edge_label_chars, path=f"{path}.label"
            ),
            "flow": _canonical_token(raw_edge["flow"], _FLOWS, path=f"{path}.flow"),
            "sync": _canonical_token(raw_edge["sync"], _SYNC_MODES, path=f"{path}.sync"),
        }
        identity = (edge["source"], edge["target"], edge["label"].lower())
        if identity in seen_edges:
            raise AppliedGraphSpecError(
                "graph_design_topology_invalid", path=path, rule="duplicate"
            )
        seen_edges.add(identity)
        edges.append(edge)

    return {"title": title, "nodes": nodes, "edges": edges}


_NODE_TECHNOLOGY = {
    "client": "Authenticated client",
    "service": "Bounded application service",
    "datastore": "Versioned durable store",
    "queue": "Durable message queue",
    "gateway": "Policy-enforcing gateway",
    "network": "Private network boundary",
    "external": "External system boundary",
    "control": "Deterministic control plane",
    "decision": "Auditable decision gate",
}
_EDGE_TECHNOLOGY = {
    "runtime": "Validated runtime contract",
    "control": "Typed control signal",
    "feedback": "Versioned feedback event",
    "deployment": "Immutable deployment control",
}


def applied_graph_edge_technology(flow: str) -> str:
    return _EDGE_TECHNOLOGY.get(flow, _EDGE_TECHNOLOGY["runtime"])


def applied_graph_node_technology(node_type: str) -> str:
    return _NODE_TECHNOLOGY.get(node_type, _NODE_TECHNOLOGY["service"])


def _stable_group_id(index: int) -> str:
    return f"group_{index + 1}"


def enrich_applied_graph_topology(
    draft: dict[str, Any],
    *,
    spec: AppliedGraphSpec,
    architect_plan: Any,
) -> GraphData:
    nodes = [
        {
            "id": node["id"],
            "label": node["label"],
            "type": node["type"],
            "technology": applied_graph_node_technology(node["type"]),
            "description": node["responsibility"],
            "tier": node["tier"],
            "lane": node["lane"],
            "detail": None,
            "layer": "architecture",
            "design_origin": "applied",
        }
        for node in draft["nodes"]
    ]
    edges = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": edge["label"],
            "technology": applied_graph_edge_technology(edge["flow"]),
            "sync": edge["sync"],
            "description": edge["label"],
            "flow": edge["flow"],
            **({"type": "loop"} if edge["flow"] == "feedback" else {}),
        }
        for edge in draft["edges"]
    ]

    group_keys: list[tuple[str, str]] = []
    for node in draft["nodes"]:
        key = (node["group"], node["group_kind"])
        if key not in group_keys:
            group_keys.append(key)
    groups = [
        {
            "id": _stable_group_id(index),
            "label": label,
            "kind": kind,
            "nodeIds": [
                node["id"]
                for node in draft["nodes"]
                if (node["group"], node["group_kind"]) == (label, kind)
            ],
        }
        for index, (label, kind) in enumerate(group_keys)
    ]

    parent_edges = {edge["target"]: edge for edge in draft["edges"][: max(0, len(nodes) - 1)]}
    sequence_by_step: dict[int, dict[str, Any]] = {}
    for node in draft["nodes"]:
        step = node["sequence_step"]
        edge = parent_edges.get(node["id"])
        if step <= 0 or edge is None:
            continue
        entry = sequence_by_step.setdefault(step, {"nodes": [], "descriptions": []})
        for node_id in (edge["source"], edge["target"]):
            if node_id not in entry["nodes"]:
                entry["nodes"].append(node_id)
        if edge["label"] not in entry["descriptions"]:
            entry["descriptions"].append(edge["label"])
    sequence = [
        {
            "step": index,
            "nodes": value["nodes"],
            "description": "; ".join(value["descriptions"]),
        }
        for index, (_authored_step, value) in enumerate(sorted(sequence_by_step.items()), 1)
    ]

    plan = architect_plan if isinstance(architect_plan, dict) else {}
    raw_assumptions = plan.get("assumptions")
    assumptions = [
        " ".join(item.split())
        for item in (raw_assumptions if isinstance(raw_assumptions, list) else [])
        if isinstance(item, str) and item.strip() and len(" ".join(item.split())) <= spec.assumption_chars
    ]
    return {
        "graph_type": "architecture",
        "title": draft["title"],
        "nodes": nodes,  # type: ignore[typeddict-item]
        "edges": edges,  # type: ignore[typeddict-item]
        "sequence": sequence,
        "groups": groups,
        "design_origin": "applied",
        "resolved_complexity": spec.depth,
        "assumptions": assumptions,
    }


def worst_case_topology_chars(spec: AppliedGraphSpec) -> int:
    nodes = [
        {
            "label": "l" * spec.node_label_chars,
            "type": "service",
            "tier": "private",
            "lane": "main",
            "responsibility": "r" * spec.responsibility_chars,
            "group": "g" * spec.group_label_chars,
            "group_kind": "runtime",
            "parent_index": _ROOT_PARENT_INDEX if index == 0 else 0,
            "parent_label": "" if index == 0 else "e" * spec.edge_label_chars,
            "parent_flow": "runtime",
            "parent_sync": "sync",
            "sequence_step": index,
        }
        for index in range(spec.safety_max_nodes)
    ]
    tree_edge_count = max(0, len(nodes) - 1)
    cross_links = [
        {
            "source_index": index % len(nodes),
            "target_index": (index + 1) % len(nodes),
            "label": "e" * spec.edge_label_chars,
            "flow": "runtime",
            "sync": "sync",
        }
        for index in range(max(0, spec.safety_max_edges - tree_edge_count))
    ]
    return len(json.dumps({"title": "t" * spec.title_chars, "nodes": nodes, "cross_links": cross_links}))
