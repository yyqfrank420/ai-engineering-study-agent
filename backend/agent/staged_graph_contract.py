"""Pure request-scoped graph planning contract.

This module owns the stable boundary between a staged graph generator and the
existing ``GraphData`` transport.  It accepts ordinary mappings so LangGraph
state and persisted JSON can pass through unchanged, but every public
transformation returns plain JSON-compatible dictionaries.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Literal, NotRequired, TypedDict


NodeType = Literal[
    "client",
    "service",
    "datastore",
    "queue",
    "gateway",
    "network",
    "external",
    "control",
    "decision",
]
Flow = Literal["runtime", "control", "feedback", "deployment"]
GroupKind = Literal["runtime", "data", "operations", "delivery", "external"]

# Model schemas import these limits so provider admission cannot be looser than
# the authoritative server contract.
TITLE_MAX_CHARS = 100
ASSUMPTION_MAX_CHARS = 240
COMPONENT_LABEL_MAX_CHARS = 60
COMPONENT_RESPONSIBILITY_MAX_CHARS = 220
GROUP_LABEL_MAX_CHARS = 80
CONNECTION_LABEL_MAX_CHARS = 100


class CapabilityPlan(TypedDict):
    external_effects: bool
    retrieval_or_reuse: bool
    learning_or_release: bool


class ComponentPlan(TypedDict):
    model_index: int
    label: str
    type: NodeType
    responsibility: str
    group_label: str
    group_kind: GroupKind
    primary_flow_member: bool
    server_id: NotRequired[str]


class ConnectionPlan(TypedDict):
    source_id: str
    target_id: str
    label: str
    flow: Flow
    sync: Literal["sync", "async"]


class StagedGraphBuild(TypedDict):
    request_id: str
    title: str
    assumptions: list[str]
    root_index: int
    capabilities: CapabilityPlan
    components: list[ComponentPlan]
    connections: list[ConnectionPlan]
    maturity: Literal["prototype", "production"]
    source: str
    stage: str
    base_graph: NotRequired[dict[str, Any]]
    base_graph_version: NotRequired[str]
    attempts: NotRequired[list[dict[str, Any]]]
    candidate_snapshot: NotRequired[dict[str, Any]]
    accepted_snapshot: NotRequired[dict[str, Any]]
    component_fingerprint: NotRequired[str]
    connection_fingerprint: NotRequired[str]
    gate_results: NotRequired[dict[str, Any]]
    failure: NotRequired[dict[str, Any]]
    graph_contract: NotRequired[dict[str, Any]]


class GraphContractError(ValueError):
    """A deterministic field-level rejection from the staged graph boundary."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.path = path


_NODE_TYPES = frozenset(NodeType.__args__)
_FLOWS = frozenset(Flow.__args__)
_GROUP_KINDS = frozenset(GroupKind.__args__)
_SYNC_MODES = frozenset(("sync", "async"))
_PRODUCTION_PROOFS = (
    "audit_and_provenance",
    "authorization_and_compensation",
    "learning_and_release",
    "retrieval_and_reuse_trust",
    "state_effect_reconciliation",
)
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


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GraphContractError("must be an object", path=path)
    return value


def _text(value: Any, path: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise GraphContractError("must be a string", path=path)
    normalized = " ".join(value.split())
    if not normalized:
        raise GraphContractError("must not be blank", path=path)
    if len(normalized) > limit:
        raise GraphContractError(f"must be at most {limit} characters", path=path)
    return normalized


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphContractError("must be an integer", path=path)
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:56] or "group"


def _unique_id(seed: str, used: set[str]) -> str:
    candidate = seed
    suffix = 2
    while candidate in used:
        candidate = f"{seed}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _normalise_capabilities(value: Any) -> CapabilityPlan:
    raw = _mapping(value, "capabilities")
    expected = {
        "external_effects",
        "retrieval_or_reuse",
        "learning_or_release",
    }
    extra = set(raw) - expected
    if extra:
        raise GraphContractError("contains unknown capability", path="capabilities")
    normalized: CapabilityPlan = {}
    for name in sorted(expected):
        enabled = raw.get(name, False)
        if not isinstance(enabled, bool):
            raise GraphContractError("must be a boolean", path=f"capabilities.{name}")
        normalized[name] = enabled  # type: ignore[literal-required]
    return normalized


def _normalise_component(value: Any, position: int) -> ComponentPlan:
    raw = _mapping(value, f"components[{position}]")
    model_index = _integer(
        raw.get("model_index"), f"components[{position}].model_index"
    )
    node_type = raw.get("type")
    if node_type not in _NODE_TYPES:
        raise GraphContractError(
            "has an invalid node type", path=f"components[{position}].type"
        )
    group_kind = raw.get("group_kind")
    if group_kind not in _GROUP_KINDS:
        raise GraphContractError(
            "has an invalid group kind", path=f"components[{position}].group_kind"
        )
    primary = raw.get("primary_flow_member")
    if not isinstance(primary, bool):
        raise GraphContractError(
            "must be a boolean", path=f"components[{position}].primary_flow_member"
        )
    component: ComponentPlan = {
        "model_index": model_index,
        "label": _text(
            raw.get("label"),
            f"components[{position}].label",
            limit=COMPONENT_LABEL_MAX_CHARS,
        ),
        "type": node_type,
        "responsibility": _text(
            raw.get("responsibility"),
            f"components[{position}].responsibility",
            limit=COMPONENT_RESPONSIBILITY_MAX_CHARS,
        ),
        "group_label": _text(
            raw.get("group_label"),
            f"components[{position}].group_label",
            limit=GROUP_LABEL_MAX_CHARS,
        ),
        "group_kind": group_kind,
        "primary_flow_member": primary,
    }
    if "server_id" in raw:
        component["server_id"] = _text(
            raw["server_id"], f"components[{position}].server_id", limit=80
        )
    return component


def _normalise_connection(value: Any, position: int) -> ConnectionPlan:
    raw = _mapping(value, f"connections[{position}]")
    flow = raw.get("flow")
    sync = raw.get("sync")
    if flow not in _FLOWS:
        raise GraphContractError(
            "has an invalid flow", path=f"connections[{position}].flow"
        )
    if sync not in _SYNC_MODES:
        raise GraphContractError(
            "has an invalid sync mode", path=f"connections[{position}].sync"
        )
    # Model indexes are allowed as endpoint references before server IDs exist.
    source = raw.get("source_id")
    target = raw.get("target_id")
    if isinstance(source, int) and not isinstance(source, bool):
        source = str(source)
    if isinstance(target, int) and not isinstance(target, bool):
        target = str(target)
    return {
        "source_id": _text(source, f"connections[{position}].source_id", limit=80),
        "target_id": _text(target, f"connections[{position}].target_id", limit=80),
        "label": _text(
            raw.get("label"),
            f"connections[{position}].label",
            limit=CONNECTION_LABEL_MAX_CHARS,
        ),
        "flow": flow,
        "sync": sync,
    }


def _normalise_build(build: Mapping[str, Any]) -> StagedGraphBuild:
    request_id = _text(build.get("request_id"), "request_id", limit=128)
    title = _text(build.get("title"), "title", limit=TITLE_MAX_CHARS)
    maturity = build.get("maturity")
    if maturity not in {"prototype", "production"}:
        raise GraphContractError("must be prototype or production", path="maturity")
    root_index = _integer(build.get("root_index"), "root_index")
    raw_components = build.get("components")
    raw_connections = build.get("connections")
    raw_assumptions = build.get("assumptions")
    if not isinstance(raw_components, list) or not raw_components:
        raise GraphContractError("must be a non-empty array", path="components")
    if not isinstance(raw_connections, list):
        raise GraphContractError("must be an array", path="connections")
    if not isinstance(raw_assumptions, list):
        raise GraphContractError("must be an array", path="assumptions")
    components = [
        _normalise_component(value, index) for index, value in enumerate(raw_components)
    ]
    connections = [
        _normalise_connection(value, index)
        for index, value in enumerate(raw_connections)
    ]
    assumptions = [
        _text(value, f"assumptions[{index}]", limit=ASSUMPTION_MAX_CHARS)
        for index, value in enumerate(raw_assumptions)
    ]
    model_indexes = [component["model_index"] for component in components]
    if len(model_indexes) != len(set(model_indexes)):
        raise GraphContractError("must be unique", path="components.model_index")
    component_identities = [
        (component["label"].casefold(), component["type"]) for component in components
    ]
    if len(component_identities) != len(set(component_identities)):
        raise GraphContractError(
            "label and type pairs must be unique", path="components"
        )
    if root_index not in set(model_indexes):
        raise GraphContractError("must identify a component", path="root_index")
    server_ids = [
        component.get("server_id")
        for component in components
        if component.get("server_id")
    ]
    if len(server_ids) != len(set(server_ids)):
        raise GraphContractError("must be unique", path="components.server_id")
    source = _text(build.get("source", "generated"), "source", limit=80)
    stage = _text(build.get("stage", "planned"), "stage", limit=80)
    normalized: StagedGraphBuild = {
        "request_id": request_id,
        "title": title,
        "assumptions": assumptions,
        "root_index": root_index,
        "capabilities": _normalise_capabilities(build.get("capabilities", {})),
        "components": components,
        "connections": connections,
        "maturity": maturity,
        "source": source,
        "stage": stage,
    }
    for field in (
        "base_graph",
        "base_graph_version",
        "attempts",
        "candidate_snapshot",
        "accepted_snapshot",
        "gate_results",
        "failure",
        "graph_contract",
    ):
        if field in build:
            normalized[field] = deepcopy(build[field])  # type: ignore[literal-required]
    return normalized


def _base_node_ids(build: Mapping[str, Any]) -> set[str]:
    base_graph = build.get("base_graph")
    if not isinstance(base_graph, Mapping):
        return set()
    nodes = base_graph.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {
        node["id"]
        for node in nodes
        if isinstance(node, Mapping)
        and isinstance(node.get("id"), str)
        and node["id"].strip()
    }


def _existing_component_ids(build: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """Find unambiguous base IDs by stable labels for a graph reconstructed without a contract."""
    base_graph = build.get("base_graph")
    if not isinstance(base_graph, Mapping) or not isinstance(
        base_graph.get("nodes"), list
    ):
        return {}
    candidates: dict[tuple[str, str], list[str]] = {}
    for node in base_graph["nodes"]:
        if not isinstance(node, Mapping):
            continue
        label, node_type, node_id = node.get("label"), node.get("type"), node.get("id")
        if all(
            isinstance(value, str) and value for value in (label, node_type, node_id)
        ):
            candidates.setdefault((label, node_type), []).append(node_id)
    return {key: values[0] for key, values in candidates.items() if len(values) == 1}


def _resolve_endpoint(
    endpoint: str,
    components: list[ComponentPlan],
    ids_by_index: dict[int, str],
    prior_ids: dict[str, str],
) -> str:
    if endpoint in prior_ids:
        return prior_ids[endpoint]
    if endpoint in ids_by_index.values():
        return endpoint
    try:
        model_index = int(endpoint)
    except ValueError as exc:
        raise GraphContractError(
            "does not identify a component", path="connections.endpoint"
        ) from exc
    if str(model_index) != endpoint or model_index not in ids_by_index:
        raise GraphContractError(
            "does not identify a component", path="connections.endpoint"
        )
    return ids_by_index[model_index]


def assign_server_ids(build: Mapping[str, Any]) -> dict[str, Any]:
    """Return a plan with stable IDs for retained components and deterministic IDs for new ones."""
    normalized = _normalise_build(build)
    used_ids = _base_node_ids(normalized)
    retained_ids = _existing_component_ids(normalized)
    components: list[ComponentPlan] = []
    ids_by_index: dict[int, str] = {}
    prior_ids: dict[str, str] = {}
    for component in normalized["components"]:
        prior_id = component.get("server_id")
        candidate = prior_id or retained_ids.get(
            (component["label"], component["type"])
        )
        if candidate and (
            candidate not in used_ids or candidate in _base_node_ids(normalized)
        ):
            server_id = candidate
            used_ids.add(server_id)
        else:
            server_id = _unique_id(f"n{component['model_index'] + 1}", used_ids)
        updated = {**component, "server_id": server_id}
        components.append(updated)
        ids_by_index[component["model_index"]] = server_id
        if prior_id:
            prior_ids[prior_id] = server_id
    connections: list[ConnectionPlan] = []
    for connection in normalized["connections"]:
        source = _resolve_endpoint(
            connection["source_id"], components, ids_by_index, prior_ids
        )
        target = _resolve_endpoint(
            connection["target_id"], components, ids_by_index, prior_ids
        )
        connections.append({**connection, "source_id": source, "target_id": target})
    assigned: dict[str, Any] = {
        **normalized,
        "components": components,
        "connections": connections,
    }
    assigned["component_fingerprint"] = component_fingerprint(assigned)
    assigned["connection_fingerprint"] = connection_fingerprint(assigned)
    return assigned


def validate_staged_graph_build(build: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a fully assigned plan and return its normalized JSON representation."""
    normalized = _normalise_build(build)
    components = normalized["components"]
    ids = [component.get("server_id") for component in components]
    if any(not node_id for node_id in ids):
        raise GraphContractError(
            "requires assigned server IDs", path="components.server_id"
        )
    node_ids = {node_id for node_id in ids if node_id}
    if len(node_ids) != len(components):
        raise GraphContractError("must be unique", path="components.server_id")
    root = next(
        component
        for component in components
        if component["model_index"] == normalized["root_index"]
    )
    if not root["primary_flow_member"]:
        raise GraphContractError("must be a primary flow member", path="root_index")
    seen_edges: set[tuple[str, str, str]] = set()
    for index, connection in enumerate(normalized["connections"]):
        source, target = connection["source_id"], connection["target_id"]
        if source not in node_ids or target not in node_ids:
            raise GraphContractError(
                "must reference assigned component IDs", path=f"connections[{index}]"
            )
        if source == target:
            raise GraphContractError(
                "cannot be a self-loop", path=f"connections[{index}]"
            )
        identity = (source, target, connection["label"].casefold())
        if identity in seen_edges:
            raise GraphContractError(
                "duplicates an existing connection", path=f"connections[{index}]"
            )
        seen_edges.add(identity)
    _primary_distances(normalized)
    return normalized


def _primary_distances(build: Mapping[str, Any]) -> dict[str, int]:
    components = build["components"]
    primary_ids = {
        component["server_id"]
        for component in components
        if component["primary_flow_member"]
    }
    root = next(
        component
        for component in components
        if component["model_index"] == build["root_index"]
    )["server_id"]
    adjacency = {node_id: [] for node_id in primary_ids}
    for connection in build["connections"]:
        if (
            connection["flow"] in {"runtime", "control"}
            and connection["source_id"] in primary_ids
            and connection["target_id"] in primary_ids
        ):
            adjacency[connection["source_id"]].append(connection["target_id"])
    distances = {root: 0}
    pending: deque[str] = deque([root])
    while pending:
        current = pending.popleft()
        for target in sorted(adjacency[current]):
            if target not in distances:
                distances[target] = distances[current] + 1
                pending.append(target)
    missing = primary_ids - set(distances)
    if missing:
        raise GraphContractError(
            "every primary flow member must be reachable through runtime or control connections",
            path="components.primary_flow_member",
        )
    return distances


def _stored_groups(
    build: Mapping[str, Any], existing_groups: Iterable[Mapping[str, Any]] | None
) -> list[Mapping[str, Any]]:
    if existing_groups is not None:
        return list(existing_groups)
    contract = build.get("graph_contract")
    if isinstance(contract, Mapping) and isinstance(contract.get("groups"), list):
        return [value for value in contract["groups"] if isinstance(value, Mapping)]
    base_graph = build.get("base_graph")
    if isinstance(base_graph, Mapping) and isinstance(base_graph.get("groups"), list):
        return [value for value in base_graph["groups"] if isinstance(value, Mapping)]
    return []


def derive_groups(
    build: Mapping[str, Any],
    *,
    existing_groups: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive flat groups, retaining an existing ID for an unchanged label and kind."""
    assigned = validate_staged_graph_build(assign_server_ids(build))
    available = _stored_groups(assigned, existing_groups)
    ids_by_key: dict[tuple[str, str], str] = {}
    used_ids: set[str] = set()
    for index, group in enumerate(available):
        group_id = group.get("id")
        label = group.get("label")
        kind = group.get("kind", "runtime")
        if (
            not isinstance(group_id, str)
            or not isinstance(label, str)
            or kind not in _GROUP_KINDS
        ):
            continue
        key = (" ".join(label.split()), kind)
        if key in ids_by_key and ids_by_key[key] != group_id:
            raise GraphContractError(
                "has ambiguous existing IDs", path=f"existing_groups[{index}]"
            )
        ids_by_key[key] = group_id
        used_ids.add(group_id)
    group_nodes: dict[tuple[str, str], list[str]] = {}
    for component in assigned["components"]:
        key = (component["group_label"], component["group_kind"])
        group_nodes.setdefault(key, []).append(component["server_id"])
    groups = []
    for label, kind in group_nodes:
        group_id = ids_by_key.get((label, kind)) or _unique_id(
            f"group_{_slug(label)}", used_ids
        )
        groups.append(
            {
                "id": group_id,
                "label": label,
                "kind": kind,
                "nodeIds": group_nodes[(label, kind)],
            }
        )
    return groups


def derive_sequence(build: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive shortest directed primary stages through runtime and control connections."""
    assigned = validate_staged_graph_build(assign_server_ids(build))
    distances = _primary_distances(assigned)
    stages: dict[int, list[str]] = {}
    for component in assigned["components"]:
        node_id = component["server_id"]
        if node_id in distances:
            stages.setdefault(distances[node_id], []).append(node_id)
    return [
        {
            "step": distance + 1,
            "nodes": stages[distance],
            "description": f"Primary flow stage {distance + 1}",
        }
        for distance in sorted(stages)
    ]


def production_proofs_for_capabilities(
    capabilities: Mapping[str, Any], *, maturity: str
) -> list[str]:
    """Map server-owned applicability flags to the production critic proof set."""
    normalized = _normalise_capabilities(capabilities)
    if maturity == "prototype":
        return []
    if maturity != "production":
        raise GraphContractError("must be prototype or production", path="maturity")
    proofs = {"audit_and_provenance"}
    if normalized["external_effects"]:
        proofs.update({"authorization_and_compensation", "state_effect_reconciliation"})
    if normalized["retrieval_or_reuse"]:
        proofs.add("retrieval_and_reuse_trust")
    if normalized["learning_or_release"]:
        proofs.add("learning_and_release")
    return [proof for proof in _PRODUCTION_PROOFS if proof in proofs]


def component_fingerprint(build: Mapping[str, Any]) -> str:
    normalized = _normalise_build(build)
    return _fingerprint(
        [
            {
                key: component[key]
                for key in (
                    "model_index",
                    "server_id",
                    "label",
                    "type",
                    "responsibility",
                    "group_label",
                    "group_kind",
                    "primary_flow_member",
                )
                if key in component
            }
            for component in normalized["components"]
        ]
    )


def connection_fingerprint(build: Mapping[str, Any]) -> str:
    normalized = _normalise_build(build)
    return _fingerprint(normalized["connections"])


def project_graph_data(build: Mapping[str, Any]) -> dict[str, Any]:
    """Project a valid assigned staged plan into the existing ``GraphData`` shape."""
    assigned = validate_staged_graph_build(assign_server_ids(build))
    nodes = [
        {
            "id": component["server_id"],
            "label": component["label"],
            "type": component["type"],
            "technology": _NODE_TECHNOLOGY[component["type"]],
            "description": component["responsibility"],
            "tier": None,
            "lane": "bottom" if component["group_kind"] == "operations" else "main",
            "detail": None,
            "layer": "architecture",
            "design_origin": "applied",
        }
        for component in assigned["components"]
    ]
    edges = [
        {
            "source": connection["source_id"],
            "target": connection["target_id"],
            "label": connection["label"],
            "technology": _EDGE_TECHNOLOGY[connection["flow"]],
            "sync": connection["sync"],
            "description": connection["label"],
            "flow": connection["flow"],
            "edge_id": f"applied:{connection['source_id']}__{_slug(connection['label'])}__{connection['target_id']}",
            "relation": _slug(connection["label"]),
        }
        for connection in assigned["connections"]
    ]
    graph: dict[str, Any] = {
        "graph_type": "architecture",
        "title": assigned["title"],
        "nodes": nodes,
        "edges": edges,
        "sequence": derive_sequence(assigned),
        "groups": derive_groups(assigned),
        "design_origin": "applied",
        "resolved_complexity": assigned["maturity"],
        "assumptions": assigned["assumptions"],
    }
    return graph


def reconstruct_staged_graph_build(
    graph_data: Mapping[str, Any],
    graph_contract: Mapping[str, Any] | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Recreate a plan from ``GraphData`` and preserve request metadata when stored."""
    graph = _mapping(graph_data, "graph_data")
    stored = dict(graph_contract or {})
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise GraphContractError("must contain nodes", path="graph_data.nodes")
    groups = graph.get("groups") if isinstance(graph.get("groups"), list) else []
    group_for_id: dict[str, tuple[str, str]] = {}
    for position, group in enumerate(groups):
        if not isinstance(group, Mapping):
            continue
        label = _text(
            group.get("label"),
            f"graph_data.groups[{position}].label",
            limit=GROUP_LABEL_MAX_CHARS,
        )
        kind = group.get("kind", "runtime")
        if kind not in _GROUP_KINDS:
            raise GraphContractError(
                "has an invalid kind", path=f"graph_data.groups[{position}].kind"
            )
        for node_id in group.get("nodeIds", []):
            if isinstance(node_id, str):
                if node_id in group_for_id:
                    raise GraphContractError(
                        "assigns a node to multiple groups", path="graph_data.groups"
                    )
                group_for_id[node_id] = (label, kind)
    sequence_values = [
        node_id
        for step in graph.get("sequence", [])
        if isinstance(step, Mapping)
        for node_id in step.get("nodes", [])
        if isinstance(node_id, str)
    ]
    sequence_ids = set(sequence_values)
    components: list[ComponentPlan] = []
    index_by_id: dict[str, int] = {}
    for index, node in enumerate(raw_nodes):
        raw_node = _mapping(node, f"graph_data.nodes[{index}]")
        node_id = _text(raw_node.get("id"), f"graph_data.nodes[{index}].id", limit=80)
        if node_id in index_by_id:
            raise GraphContractError(
                "duplicates a node ID", path=f"graph_data.nodes[{index}].id"
            )
        index_by_id[node_id] = index
        group_label, group_kind = group_for_id.get(node_id, ("Architecture", "runtime"))
        components.append(
            {
                "model_index": index,
                "server_id": node_id,
                "label": _text(
                    raw_node.get("label"),
                    f"graph_data.nodes[{index}].label",
                    limit=COMPONENT_LABEL_MAX_CHARS,
                ),
                "type": raw_node.get("type")
                if raw_node.get("type") in _NODE_TYPES
                else "service",
                "responsibility": _text(
                    raw_node.get("description"),
                    f"graph_data.nodes[{index}].description",
                    limit=COMPONENT_RESPONSIBILITY_MAX_CHARS,
                ),
                "group_label": group_label,
                "group_kind": group_kind,
                "primary_flow_member": node_id in sequence_ids,
            }
        )
    root_id = next(
        (node_id for node_id in sequence_values if node_id in index_by_id),
        raw_nodes[0].get("id"),
    )
    root_index = index_by_id.get(root_id)
    if root_index is None:
        raise GraphContractError(
            "does not identify a graph node", path="graph_data.sequence"
        )
    components[root_index]["primary_flow_member"] = True
    raw_edges = graph.get("edges")
    if not isinstance(raw_edges, list):
        raise GraphContractError("must be an array", path="graph_data.edges")
    connections = [
        _normalise_connection(
            {
                "source_id": edge.get("source"),
                "target_id": edge.get("target"),
                "label": edge.get("label"),
                "flow": edge.get("flow", "runtime"),
                "sync": edge.get("sync", "sync"),
            },
            index,
        )
        for index, edge in enumerate(raw_edges)
        if isinstance(edge, Mapping)
    ]
    reconstructed: dict[str, Any] = {
        "request_id": request_id or stored.get("request_id", "reconstructed"),
        "title": graph.get("title"),
        "assumptions": graph.get("assumptions", []),
        "root_index": root_index,
        "capabilities": stored.get(
            "capabilities",
            {
                "external_effects": False,
                "retrieval_or_reuse": False,
                "learning_or_release": False,
            },
        ),
        "components": components,
        "connections": connections,
        "maturity": stored.get(
            "maturity", graph.get("resolved_complexity", "prototype")
        ),
        "source": stored.get("source", "reconstructed"),
        "stage": stored.get("stage", "reconstructed"),
        "base_graph": deepcopy(dict(graph)),
        "base_graph_version": graph.get("version"),
        "graph_contract": deepcopy(stored),
    }
    return assign_server_ids(reconstructed)


def _write_set(
    value: Mapping[str, Any], *, path: str
) -> tuple[set[str], int, int, set[str]]:
    allowed = value.get("allowed_ids", [])
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) and item for item in allowed
    ):
        raise GraphContractError(
            "allowed_ids must be an array of IDs", path=f"{path}.allowed_ids"
        )
    additions = value.get("addition_count", 0)
    removals = value.get("removal_count", 0)
    if isinstance(additions, bool) or not isinstance(additions, int) or additions < 0:
        raise GraphContractError(
            "addition_count must be non-negative", path=f"{path}.addition_count"
        )
    if isinstance(removals, bool) or not isinstance(removals, int) or removals < 0:
        raise GraphContractError(
            "removal_count must be non-negative", path=f"{path}.removal_count"
        )
    incident = value.get("incident_edge_ids", [])
    if not isinstance(incident, list) or not all(
        isinstance(item, str) and item for item in incident
    ):
        raise GraphContractError(
            "incident_edge_ids must be an array of IDs",
            path=f"{path}.incident_edge_ids",
        )
    return set(allowed), additions, removals, set(incident)


def validate_component_write_set(
    base_plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    write_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Require exact component authority and immutable uncited records."""
    # Connections are authored after the component gate. Component admission
    # cannot require the new primary members to be reachable yet.
    base = assign_server_ids(base_plan)
    revised = assign_server_ids(candidate)
    allowed, additions, removals, incident = _write_set(
        write_set, path="component_write_set"
    )
    base_components = {item["server_id"]: item for item in base["components"]}
    revised_components = {item["server_id"]: item for item in revised["components"]}
    removed = set(base_components) - set(revised_components)
    added = set(revised_components) - set(base_components)
    if len(added) != additions or len(removed) != removals:
        raise GraphContractError(
            "addition or removal count does not match", path="component_write_set"
        )
    if (set(base_components) & set(revised_components)) - allowed:
        for node_id in (set(base_components) & set(revised_components)) - allowed:
            if base_components[node_id] != revised_components[node_id]:
                raise GraphContractError(
                    "changes an uncited component", path=f"components.{node_id}"
                )
    if not removed <= allowed:
        raise GraphContractError("removes an uncited component", path="components")
    _validate_component_incident_edges(base, revised, allowed, incident)
    return revised


def _edge_identity(edge: Mapping[str, Any]) -> str:
    return f"{edge['source_id']}|{edge['target_id']}|{edge['label'].casefold()}"


def _validate_component_incident_edges(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    allowed: set[str],
    incident: set[str],
) -> None:
    before = {_edge_identity(edge): edge for edge in base["connections"]}
    after = {_edge_identity(edge): edge for edge in candidate["connections"]}
    for edge_id in set(before) | set(after):
        changed = before.get(edge_id) != after.get(edge_id)
        edge = after.get(edge_id) or before[edge_id]
        touches_allowed = edge["source_id"] in allowed or edge["target_id"] in allowed
        if changed and touches_allowed and edge_id not in incident:
            raise GraphContractError(
                "changes an incident edge without authority", path="connections"
            )
        if changed and not touches_allowed:
            raise GraphContractError(
                "changes an uncited connection", path="connections"
            )


def validate_connection_write_set(
    base_plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    write_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Require exact connection authority and immutable uncited edges."""
    base = validate_staged_graph_build(assign_server_ids(base_plan))
    revised = validate_staged_graph_build(assign_server_ids(candidate))
    allowed, additions, removals, _ = _write_set(write_set, path="connection_write_set")
    before = {_edge_identity(edge): edge for edge in base["connections"]}
    after = {_edge_identity(edge): edge for edge in revised["connections"]}
    removed = set(before) - set(after)
    added = set(after) - set(before)
    if len(added) != additions or len(removed) != removals:
        raise GraphContractError(
            "addition or removal count does not match", path="connection_write_set"
        )
    changed = removed | added
    if not changed <= allowed:
        raise GraphContractError("changes an uncited connection", path="connections")
    if base["components"] != revised["components"]:
        raise GraphContractError(
            "connection writes cannot change components", path="components"
        )
    return revised


def _semantic_edge_identity(
    edge: Mapping[str, Any],
) -> tuple[str, str, str, str, str]:
    return (
        edge["source_id"],
        edge["target_id"],
        edge["label"].casefold(),
        edge["flow"],
        edge["sync"],
    )


def validate_create_connection_correction_authority(
    rejected_build: Mapping[str, Any],
    corrected_build: Mapping[str, Any],
) -> dict[str, Any]:
    """Require a control authority endpoint for new correction-time control edges."""
    # A correction can follow a connection-generation failure before the first
    # full graph is structurally valid. Component-stage state is still accepted
    # authority, so normalize its IDs without requiring connection reachability.
    rejected = assign_server_ids(rejected_build)
    corrected = validate_staged_graph_build(assign_server_ids(corrected_build))
    if rejected["components"] != corrected["components"]:
        raise GraphContractError(
            "connection correction cannot change components", path="components"
        )
    rejected_edges = {
        _semantic_edge_identity(connection) for connection in rejected["connections"]
    }
    component_types = {
        component["server_id"]: component["type"]
        for component in corrected["components"]
    }
    for connection in corrected["connections"]:
        if (
            connection["flow"] != "control"
            or _semantic_edge_identity(connection) in rejected_edges
        ):
            continue
        endpoint_types = {
            component_types[connection["source_id"]],
            component_types[connection["target_id"]],
        }
        if endpoint_types.isdisjoint({"control", "decision"}):
            raise GraphContractError(
                "new control connections require a control or decision endpoint",
                path="connections",
            )
    return corrected
