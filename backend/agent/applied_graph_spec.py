from __future__ import annotations

from collections import deque
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
_FLOWS = ("runtime", "control", "feedback", "deployment")
_SYNC_MODES = ("sync", "async")
_GROUP_KINDS = ("runtime", "data", "operations", "delivery", "external")
_NODE_TYPE_CODES = {100 + index: token for index, token in enumerate(_NODE_TYPES)}
_FLOW_CODES = {400 + index: token for index, token in enumerate(_FLOWS)}
_SYNC_CODES = {500 + index: token for index, token in enumerate(_SYNC_MODES)}
_GROUP_KIND_CODES = {600 + index: token for index, token in enumerate(_GROUP_KINDS)}
_ROOT_FIELD_COUNT = 5
_COMPONENT_FIELD_COUNT = 9
_LINK_FIELD_COUNT = 5
GRAPH_EDGE_LABEL_CHARS = 100

logger = logging.getLogger(__name__)

_ERROR_RULES = frozenset(
    {
        "blank_required",
        "bounded_identity_collision",
        "container_type",
        "duplicate",
        "invalid_enum",
        "invalid_index",
        "json_decode",
        "key_set",
        "provider_finish",
        "safety_limit",
        "topology",
        "tuple_arity",
        "value_type",
    }
)


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
        observed_index: int | None = None,
        maximum_index: int | None = None,
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
        self.observed_index = (
            observed_index
            if isinstance(observed_index, int) and not isinstance(observed_index, bool)
            else None
        )
        self.maximum_index = (
            maximum_index
            if isinstance(maximum_index, int) and not isinstance(maximum_index, bool)
            else None
        )


def applied_graph_spec(depth: str) -> AppliedGraphSpec:
    if settings.graph_safety_max_nodes > min(_NODE_TYPE_CODES):
        raise RuntimeError(
            "GRAPH_SAFETY_MAX_NODES must stay below the wire category namespace"
        )
    return AppliedGraphSpec(
        depth=depth if depth in {"low", "prototype", "production"} else "production",
        safety_max_nodes=settings.graph_safety_max_nodes,
        safety_max_edges=settings.graph_safety_max_edges,
    )


def applied_graph_topology_schema(spec: AppliedGraphSpec) -> dict[str, Any]:
    # Keep positional rows compact for Anthropic's schema compiler. It does not
    # support prefixItems, and the Anthropic adapter currently strips maxItems.
    # Other structured-output providers enforce these bounds; Python validates
    # tuple arity, aggregate capacity, and every scalar after parsing for all routes.
    integer_or_string = {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }
    root_record = {
        "type": "array",
        "maxItems": _ROOT_FIELD_COUNT,
        "items": integer_or_string,
    }
    component_record = {
        "type": "array",
        "maxItems": _COMPONENT_FIELD_COUNT,
        "items": integer_or_string,
    }
    link_record = {
        "type": "array",
        "maxItems": _LINK_FIELD_COUNT,
        "items": integer_or_string,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "root",
            "components",
            "connections",
            "composition",
        ],
        "properties": {
            "root": root_record,
            "components": {
                "type": "array",
                "maxItems": max(0, spec.safety_max_nodes - 1),
                "items": component_record,
            },
            "connections": {
                "type": "object",
                "additionalProperties": False,
                "required": ["links"],
                "properties": {
                    "links": {
                        "type": "array",
                        "maxItems": spec.safety_max_edges,
                        "items": link_record,
                    },
                },
            },
            "composition": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "steps"],
                "properties": {
                    "title": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "maxItems": spec.safety_max_nodes,
                        "items": {"type": "integer"},
                    },
                },
            },
        },
    }


def _bounded_input(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def applied_graph_topology_prompt(
    *,
    query: str,
    spec: AppliedGraphSpec,
) -> str:
    codebook = " ".join(
        f"{name}: " + ",".join(f"{code}={token}" for code, token in codes.items()) + "."
        for name, codes in (
            ("Type", _NODE_TYPE_CODES),
            ("Flow", _FLOW_CODES),
            ("Sync", _SYNC_CODES),
            ("Group kind", _GROUP_KIND_CODES),
        )
    )
    design_input = {
        "request": _bounded_input(query, spec.query_chars),
        "depth": spec.depth,
    }
    valid_example = {
        "root": ["Client", 100, "Submits one request.", "Product runtime", 600],
        "components": [
            [
                0,
                "Request gateway",
                104,
                "Validates and routes the request.",
                "Product runtime",
                600,
                "sends request",
                400,
                500,
            ],
            [
                1,
                "Result service",
                101,
                "Returns the observable outcome.",
                "Product runtime",
                600,
                "returns outcome",
                400,
                500,
            ],
        ],
        "connections": {"links": []},
        "composition": {
            "title": "Request runtime",
            "steps": [0, 1, 2],
        },
    }
    return (
        "Build the complete architecture topology for the supplied design input. Preserve every "
        "material owner, trust boundary, authoritative store, decision, runtime branch, control path, "
        "failure outcome, and delivery boundary.\n"
        "WIRE CONTRACT\n"
        "Every index is zero-based. Use these exact rows:\n"
        "root: [label:string,type:integer,responsibility:string,group_label:string,"
        "group_kind:integer]\n"
        "components[i]: [parent_index:integer,label:string,type:integer,responsibility:string,"
        "group_label:string,group_kind:integer,incoming_edge_label:string,flow:integer,"
        "sync:integer]\n"
        "connections.links[i]: [source_index:integer,target_index:integer,label:string,flow:integer,"
        "sync:integer]\n"
        "composition.title is a string. composition.steps is one flat array of integer node indexes. "
        "Do not use null, booleans, objects, omitted tuple values, or placeholder strings inside rows. "
        f"Use integer codes for type, group_kind, flow, and sync. {codebook}\n"
        "INDEX RULES\n"
        "Root is index 0 and becomes server node n1. components[i] defines node index i+1. Its parent "
        "must be an existing earlier node index from 0 through i. For example, components[5][0] may "
        "be 0 through 5; value 6 is self-reference and invalid. Link endpoints and composition steps "
        "address nodes. Never emit server "
        "node IDs, $new_node_N placeholders, forward parents, or undefined indexes.\n"
        "TOPOLOGY RULES\n"
        "Choose the number of components and links from the design. Every root and component row "
        "must carry its exact group label and kind. Reuse the same label and kind for nodes in the "
        "same group. Make the root the primary runtime entry or trigger. Do not use an internal "
        "coordinator when a client, event source, or schedule starts the flow. Tree-edge direction and "
        "its incoming label must agree: the parent sends the named data or command to the child. "
        "Include all material non-tree links. Multiple edges between the same pair need compatible, "
        "distinct contracts. Reverse edges need a distinct response, acknowledgement, feedback, or "
        "control contract. Every approval decision needs distinct approved and rejected routes. "
        "External mutations show validation, approval, execution, authoritative state, and "
        "reconciliation as separate responsibilities when those boundaries apply.\n"
        "A component earns a row when ownership, trust, authoritative state, a decision, an external "
        "action, or an outcome changes. Fold other implementation detail into its owner. An edge earns "
        "a record when its contract is needed to follow behavior or prove a guarantee. Consolidate "
        "semantic duplicates. Do not add diagram authoring, rendering, or graph-generation mechanics "
        "unless requested.\n"
        "SEQUENCE RULES\n"
        "composition.steps declares primary runtime-sequence membership. The server derives stage "
        "order from directed primary/runtime edges. A nonempty list includes root index 0. Every other "
        "member must be reachable from root through selected members. Include each node at most once. "
        "Omit offline and supporting side paths. Production depth requires a primary sequence. "
        "Prototype depth may omit it for a non-flow diagram.\n"
        "DEPTH RULES\n"
        "At low depth, include requested material runtime and control paths only. At prototype depth, "
        "use concrete buildable boundaries and applicable requested failure paths. Do not add "
        "production hardening at low or prototype depth. At production depth, include every applicable "
        "control, failure, observability, and delivery path. When applicable, include a no-effect "
        "rejection outcome, bounded compensation after an effect through normal controls, distinct "
        "retry exhaustion, success, COMMITTED, NOT_FOUND, and STILL_UNKNOWN outcomes, plus distinct "
        "canary, promotion, and rollback paths.\n"
        "OWNERSHIP AND LIMITS\n"
        "The request owns the objective, domain vocabulary, and stated constraints. The selected depth "
        "and these rules own the initial topology contract. An independent architecture review follows "
        "this reversible draft. You author title, node groups, component semantics, edge semantics, and "
        "sequence membership. The server owns stable IDs, technology, transport, edge descriptions, "
        "lanes, tiers, assumptions, positions, selections, and rendering state. The server derives each "
        "lane from its authored group kind. Do not emit server-owned fields.\n"
        f"Use at most {spec.safety_max_nodes} nodes including root and {spec.safety_max_edges} total "
        f"edges including component tree edges and links. components has at most "
        f"{max(0, spec.safety_max_nodes - 1)} rows. components plus links must not exceed "
        f"{spec.safety_max_edges}. Steps contain at most {spec.safety_max_nodes} entries. "
        "Keep title at most 100 characters, node labels at most 60, group labels at most 80, "
        f"responsibilities at most 220, and edge labels at most {spec.edge_label_chars}.\n"
        "EXAMPLE\n"
        + json.dumps(valid_example, ensure_ascii=False, separators=(",", ":"))
        + "\nUse the example only for wire shape. Author the requested domain topology. Return only compact "
        "schema-constrained JSON without indentation or line breaks.\nINPUT\n"
        + json.dumps(design_input, ensure_ascii=False, separators=(",", ":"))
    )


def _normalised_required_text(value: Any, *, path: str) -> str:
    if not isinstance(value, str):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    normalized = " ".join(value.split())
    if not normalized:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="blank_required"
        )
    return normalized


def _bounded_text(normalized: str, limit: int, *, path: str) -> str:
    if len(normalized) > limit:
        logger.info(
            "Bounded applied graph text: path=%s original_chars=%s limit=%s",
            path,
            len(normalized),
            limit,
        )
        prefix = normalized[:limit]
        if normalized[limit] != " ":
            word_boundary = prefix.rfind(" ")
            if word_boundary >= limit // 2:
                return prefix[:word_boundary]
        return prefix
    return normalized


def _required_text(value: Any, limit: int, *, path: str) -> str:
    return _bounded_text(
        _normalised_required_text(value, path=path),
        limit,
        path=path,
    )


def _coded_token(value: Any, codes: dict[int, str], *, path: str) -> str:
    """Decode canonical integer codes and normalize accepted compatibility values.

    Canonical topology output uses integer codes. Named tokens and decimal-string codes
    are accepted only as compatibility input and are normalized to their coded token.
    """
    if isinstance(value, bool):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    if isinstance(value, int):
        token = codes.get(value)
        if token is None:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="invalid_enum"
            )
        return token
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in codes.values():
            logger.info("Normalized applied graph category token: path=%s", path)
            return normalized
        numeric_token = {str(code): token for code, token in codes.items()}.get(
            normalized
        )
        if numeric_token is not None:
            logger.info("Normalized applied graph category code: path=%s", path)
            return numeric_token
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="invalid_enum"
        )
    raise AppliedGraphSpecError(
        "graph_design_schema_invalid", path=path, rule="value_type"
    )


def _required_index(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type"
        )
    return value


def _required_tuple(value: Any, size: int, *, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="container_type"
        )
    if len(value) != size:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="tuple_arity"
        )
    return value


def _raise_topology(
    path: str,
    *,
    observed_index: int | None = None,
    maximum_index: int | None = None,
) -> None:
    raise AppliedGraphSpecError(
        "graph_design_topology_invalid",
        path=path,
        rule="topology",
        observed_index=observed_index,
        maximum_index=maximum_index,
    )


def _validate_component(
    component: list[Any],
    *,
    node_index: int,
    field_offset: int,
    path: str,
    spec: AppliedGraphSpec,
    group_sources: dict[tuple[str, str], str],
) -> dict[str, Any]:
    group_label_index = field_offset + 3
    group_kind_index = field_offset + 4
    full_group = _normalised_required_text(
        component[group_label_index], path=f"{path}[{group_label_index}]"
    )
    group = _bounded_text(
        full_group,
        spec.group_label_chars,
        path=f"{path}[{group_label_index}]",
    )
    group_kind = _coded_token(
        component[group_kind_index],
        _GROUP_KIND_CODES,
        path=f"{path}[{group_kind_index}]",
    )
    group_key = (group, group_kind)
    prior_group = group_sources.get(group_key)
    if prior_group is not None and prior_group != full_group:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid",
            path=f"{path}[{group_label_index}]",
            rule="bounded_identity_collision",
        )
    group_sources[group_key] = full_group
    return {
        "id": f"n{node_index + 1}",
        "label": _required_text(
            component[field_offset],
            spec.node_label_chars,
            path=f"{path}[{field_offset}]",
        ),
        "type": _coded_token(
            component[field_offset + 1],
            _NODE_TYPE_CODES,
            path=f"{path}[{field_offset + 1}]",
        ),
        "responsibility": _required_text(
            component[field_offset + 2],
            spec.responsibility_chars,
            path=f"{path}[{field_offset + 2}]",
        ),
        "group": group,
        "group_kind": group_kind,
    }


def _validate_components(
    raw_root: Any,
    raw_components: list[Any],
    spec: AppliedGraphSpec,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    root = _required_tuple(raw_root, _ROOT_FIELD_COUNT, path="root")
    group_sources: dict[tuple[str, str], str] = {}
    components = [
        _validate_component(
            root,
            node_index=0,
            field_offset=0,
            path="root",
            spec=spec,
            group_sources=group_sources,
        )
    ]
    tree_edges: list[dict[str, str]] = []
    component_rows = [
        _required_tuple(
            raw_component,
            _COMPONENT_FIELD_COUNT,
            path=f"components[{component_index - 1}]",
        )
        for component_index, raw_component in enumerate(raw_components, start=1)
    ]
    parent_indexes = [
        _required_index(component[0], path=f"components[{index}][0]")
        for index, component in enumerate(component_rows)
    ]
    for component_index, (component, parent_index) in enumerate(
        zip(component_rows, parent_indexes, strict=True),
        start=1,
    ):
        path = f"components[{component_index - 1}]"
        if parent_index < 0 or parent_index >= component_index:
            _raise_topology(
                f"{path}[0]",
                observed_index=parent_index,
                maximum_index=component_index - 1,
            )
        components.append(
            _validate_component(
                component,
                node_index=component_index,
                field_offset=1,
                path=path,
                spec=spec,
                group_sources=group_sources,
            )
        )
        tree_edges.append(
            {
                "source": f"n{parent_index + 1}",
                "target": f"n{component_index + 1}",
                "label": _required_text(
                    component[6], spec.edge_label_chars, path=f"{path}[6]"
                ),
                "flow": _coded_token(component[7], _FLOW_CODES, path=f"{path}[7]"),
                "sync": _coded_token(component[8], _SYNC_CODES, path=f"{path}[8]"),
            }
        )
    return components, tree_edges


def _validate_links(
    raw_links: list[Any],
    node_count: int,
    tree_edges: list[dict[str, str]],
    spec: AppliedGraphSpec,
) -> list[dict[str, str]]:
    link_records = [
        _required_tuple(
            raw_edge,
            _LINK_FIELD_COUNT,
            path=f"connections.links[{link_index}]",
        )
        for link_index, raw_edge in enumerate(raw_links)
    ]
    endpoint_rows = [
        (
            _required_index(
                edge_record[0], path=f"connections.links[{link_index}][0]"
            ),
            _required_index(
                edge_record[1], path=f"connections.links[{link_index}][1]"
            ),
        )
        for link_index, edge_record in enumerate(link_records)
    ]

    edges = list(tree_edges)
    seen_edges = {
        (edge["source"], edge["target"], edge["label"].lower()) for edge in tree_edges
    }
    for link_index, (edge_record, endpoints) in enumerate(
        zip(link_records, endpoint_rows, strict=True)
    ):
        path = f"connections.links[{link_index}]"
        source_index, target_index = endpoints
        if source_index < 0 or source_index >= node_count:
            _raise_topology(f"{path}[0]")
        if target_index < 0 or target_index >= node_count:
            _raise_topology(f"{path}[1]")
        if source_index == target_index:
            logger.info(
                "Rejected applied graph self-link: node_count=%s link_count=%s",
                node_count,
                len(link_records),
            )
            _raise_topology(path)
        edge = {
            "source": f"n{source_index + 1}",
            "target": f"n{target_index + 1}",
            "label": _required_text(
                edge_record[2], spec.edge_label_chars, path=f"{path}[2]"
            ),
            "flow": _coded_token(edge_record[3], _FLOW_CODES, path=f"{path}[3]"),
            "sync": _coded_token(edge_record[4], _SYNC_CODES, path=f"{path}[4]"),
        }
        identity = (edge["source"], edge["target"], edge["label"].lower())
        if identity in seen_edges:
            raise AppliedGraphSpecError(
                "graph_design_topology_invalid", path=path, rule="duplicate"
            )
        seen_edges.add(identity)
        edges.append(edge)
    return edges


def _derive_sequence_steps(
    raw_steps: list[Any],
    node_count: int,
    tree_edges: list[dict[str, str]],
    edges: list[dict[str, str]],
    *,
    require_sequence: bool,
) -> list[int]:
    if require_sequence and not raw_steps:
        _raise_topology("composition.steps")
    seen_components: set[int] = set()
    component_paths: dict[int, str] = {}
    for item_index, value in enumerate(raw_steps):
        component_path = f"composition.steps[{item_index}]"
        component_index = _required_index(value, path=component_path)
        if component_index < 0 or component_index >= node_count:
            _raise_topology(component_path)
        if component_index in seen_components:
            raise AppliedGraphSpecError(
                "graph_design_topology_invalid",
                path=component_path,
                rule="duplicate",
            )
        seen_components.add(component_index)
        component_paths[component_index] = component_path

    if raw_steps and 0 not in seen_components:
        _raise_topology("composition.steps[0]")

    outgoing_targets: dict[int, set[int]] = {}
    primary_runtime_edges = [
        *tree_edges,
        *(edge for edge in edges if edge["flow"] == "runtime"),
    ]
    for edge in primary_runtime_edges:
        source_index = int(edge["source"][1:]) - 1
        target_index = int(edge["target"][1:]) - 1
        if source_index in seen_components and target_index in seen_components:
            outgoing_targets.setdefault(source_index, set()).add(target_index)

    sequence_steps = [0] * node_count
    if not seen_components:
        return sequence_steps
    sequence_steps[0] = 1
    frontier = deque([0])
    while frontier:
        source_index = frontier.popleft()
        for target_index in sorted(outgoing_targets.get(source_index, set())):
            if sequence_steps[target_index] > 0:
                continue
            sequence_steps[target_index] = sequence_steps[source_index] + 1
            frontier.append(target_index)

    reached_components = {
        index for index, step in enumerate(sequence_steps) if step > 0
    }
    unreachable = sorted(seen_components - reached_components)
    if unreachable:
        _raise_topology(component_paths[unreachable[0]])
    return sequence_steps


def validate_applied_graph_topology(
    payload: Any,
    spec: AppliedGraphSpec,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "root",
        "components",
        "connections",
        "composition",
    }:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="$", rule="key_set"
        )

    raw_root = payload["root"]
    raw_components = payload["components"]
    raw_connections = payload["connections"]
    raw_composition = payload["composition"]
    if not isinstance(raw_connections, dict) or set(raw_connections) != {"links"}:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="connections", rule="key_set"
        )
    if not isinstance(raw_composition, dict) or set(raw_composition) != {
        "title",
        "steps",
    }:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="composition", rule="key_set"
        )
    if not isinstance(raw_components, list):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="components", rule="container_type"
        )
    node_count = len(raw_components) + 1
    if node_count > spec.safety_max_nodes:
        raise AppliedGraphSpecError(
            "graph_design_node_safety_limit",
            node_count=node_count,
            path="components",
            rule="safety_limit",
        )
    raw_links = raw_connections["links"]
    raw_steps = raw_composition["steps"]
    for value, path in (
        (raw_links, "connections.links"),
        (raw_steps, "composition.steps"),
    ):
        if isinstance(value, list):
            continue
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="container_type"
        )
    edge_count = len(raw_components) + len(raw_links)
    if edge_count > spec.safety_max_edges:
        raise AppliedGraphSpecError(
            "graph_design_edge_safety_limit",
            node_count=node_count,
            edge_count=edge_count,
            path="connections",
            rule="safety_limit",
        )
    components, tree_edges = _validate_components(raw_root, raw_components, spec)
    edges = _validate_links(raw_links, node_count, tree_edges, spec)
    sequence_steps = _derive_sequence_steps(
        raw_steps,
        node_count,
        tree_edges,
        edges,
        require_sequence=spec.depth == "production",
    )
    nodes = [
        {
            **component,
            "tier": None,
            "lane": (
                "bottom" if component["group_kind"] == "operations" else "main"
            ),
            "sequence_step": sequence_step,
        }
        for component, sequence_step in zip(components, sequence_steps, strict=True)
    ]
    title = _required_text(
        raw_composition["title"], spec.title_chars, path="composition.title"
    )
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

    parent_edges = {
        edge["target"]: edge for edge in draft["edges"][: max(0, len(nodes) - 1)]
    }
    sequence_by_step: dict[int, dict[str, Any]] = {}
    for node in draft["nodes"]:
        step = node["sequence_step"]
        edge = parent_edges.get(node["id"])
        if step <= 0:
            continue
        entry = sequence_by_step.setdefault(step, {"nodes": [], "descriptions": []})
        if node["id"] not in entry["nodes"]:
            entry["nodes"].append(node["id"])
        description = edge["label"] if edge is not None else node["responsibility"]
        if description not in entry["descriptions"]:
            entry["descriptions"].append(description)
    sequence = [
        {
            "step": index,
            "nodes": value["nodes"],
            "description": "; ".join(value["descriptions"]),
        }
        for index, (_authored_step, value) in enumerate(
            sorted(sequence_by_step.items()), 1
        )
    ]

    plan = architect_plan if isinstance(architect_plan, dict) else {}
    raw_assumptions = plan.get("assumptions")
    assumptions = [
        " ".join(item.split())
        for item in (raw_assumptions if isinstance(raw_assumptions, list) else [])
        if isinstance(item, str)
        and item.strip()
        and len(" ".join(item.split())) <= spec.assumption_chars
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
    node_count = max(0, spec.safety_max_nodes)
    root = [
        "l" * spec.node_label_chars,
        max(_NODE_TYPE_CODES),
        "r" * spec.responsibility_chars,
        "g" * spec.group_label_chars,
        max(_GROUP_KIND_CODES),
    ]
    components = [
        [
            index,
            "l" * spec.node_label_chars,
            max(_NODE_TYPE_CODES),
            "r" * spec.responsibility_chars,
            f"{index:02d}" + "g" * max(0, spec.group_label_chars - 2),
            max(_GROUP_KIND_CODES),
            "e" * spec.edge_label_chars,
            max(_FLOW_CODES),
            max(_SYNC_CODES),
        ]
        for index in range(max(0, node_count - 1))
    ]
    link_count = (
        max(0, spec.safety_max_edges - len(components)) if node_count > 1 else 0
    )
    link_endpoints = [
        (source, target)
        for source in reversed(range(node_count))
        for target in reversed(range(node_count))
        if source != target and target != source + 1
    ][:link_count]
    links = [
        [
            source,
            target,
            "e" * spec.edge_label_chars,
            max(_FLOW_CODES),
            max(_SYNC_CODES),
        ]
        for source, target in link_endpoints
    ]
    payload = {
        "root": root,
        "components": components,
        "connections": {"links": links},
        "composition": {
            "title": "t" * spec.title_chars,
            "steps": list(range(1, len(components) + 1)),
        },
    }
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
