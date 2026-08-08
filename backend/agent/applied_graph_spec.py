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
_FLOWS = ("runtime", "control", "feedback", "deployment")
_SYNC_MODES = ("sync", "async")
_GROUP_KINDS = ("runtime", "data", "operations", "delivery", "external")
_NODE_TYPE_CODES = {100 + index: token for index, token in enumerate(_NODE_TYPES)}
_FLOW_CODES = {400 + index: token for index, token in enumerate(_FLOWS)}
_SYNC_CODES = {500 + index: token for index, token in enumerate(_SYNC_MODES)}
_GROUP_KIND_CODES = {600 + index: token for index, token in enumerate(_GROUP_KINDS)}
_ROOT_FIELD_COUNT = 4
_COMPONENT_FIELD_COUNT = 8
_LINK_FIELD_COUNT = 5
_GROUP_FIELD_COUNT = 2
GRAPH_EDGE_LABEL_CHARS = 100

logger = logging.getLogger(__name__)

_ERROR_RULES = frozenset({
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
    if settings.graph_safety_max_nodes > min(_NODE_TYPE_CODES):
        raise RuntimeError(
            "GRAPH_SAFETY_MAX_NODES must stay below the wire category namespace"
        )
    return AppliedGraphSpec(
        depth=depth if depth in {"low", "prototype", "production"} else "production",
        safety_max_nodes=settings.graph_safety_max_nodes,
        safety_max_edges=settings.graph_safety_max_edges,
    )


def applied_graph_topology_schema(_spec: AppliedGraphSpec) -> dict[str, Any]:
    integer_or_string = {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }
    root_record = {"type": "array", "items": integer_or_string}
    component_record = {"type": "array", "items": integer_or_string}
    link_record = {"type": "array", "items": integer_or_string}
    group_record = {"type": "array", "items": integer_or_string}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["root", "components", "connections", "composition"],
        "properties": {
            "root": root_record,
            "components": {"type": "array", "items": component_record},
            "connections": {
                "type": "object",
                "additionalProperties": False,
                "required": ["links"],
                "properties": {
                    "links": {"type": "array", "items": link_record},
                },
            },
            "composition": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "groups", "steps"],
                "properties": {
                    "title": {"type": "string"},
                    "groups": {"type": "array", "items": group_record},
                    "steps": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
        },
    }


def _bounded_input(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _without_status_update(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key != "status_update"}


def applied_graph_topology_prompt(
    *,
    query: str,
    architect_plan: Any,
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
        "reviewed_plan": _without_status_update(architect_plan),
    }
    return (
        "Build the complete architecture topology from the supplied design input. Include every "
        "material responsibility, ownership boundary, runtime branch, control path, data store, "
        "delivery path, and failure outcome needed by this specific system. Use these exact tuple "
        "layouts: root is [label,type,responsibility,group_index]; every remaining component is "
        "[parent_index,label,type,responsibility,group_index,incoming_edge_label,flow,sync]; link "
        "rows are [source_index,target_index,label,flow,sync]; group definition rows are "
        "[label,kind]. Categorical tuple fields and group kind use "
        f"integer codes. {codebook} Use the integer, never its name, in the wire object. Choose the "
        "number of components, groups, and "
        "links from the design. Never merge distinct owners, trust "
        "boundaries, authoritative stores, decisions, or failure outcomes to make the diagram "
        "smaller. Order components in a stable visual reading order. The root is component 0. A row "
        "at components[i] defines component i+1 and its one incoming tree edge. Parent indexes are "
        "zero-based and must be smaller than the component index, which makes one rooted acyclic "
        "topology. For example, components[0] must use parent 0 and components[4] may use parent "
        "0 through 4, never 5. Define groups before assigning their zero-based indexes in the root and "
        "component rows. Every component must reference exactly one group. Links use component "
        "indexes starting with root 0. "
        "Composition steps use the same indexes but allow only non-root components 1 through the "
        "final component. Put parallel incoming edges in the same step, keep each component "
        "in at most one step, and omit supporting edges from steps. Include all material "
        "non-tree links. Every approval decision "
        "needs distinct approved and rejected routes. Rejection is a no-effect outcome. A failure "
        "after an effect uses a separate bounded compensation route through the normal controls. "
        "Retry exhaustion, success, COMMITTED, NOT_FOUND, and STILL_UNKNOWN remain distinct outcomes "
        "when they apply. Canary, promotion, and rollback remain distinct delivery paths when they "
        "apply. Edge labels state the visible action or control contract. External mutations show "
        "validation, approval, execution, authoritative state, and reconciliation as distinct "
        "responsibilities when those boundaries apply. Keep the title at most 100 characters, node "
        "labels at most 60 characters, group labels at most 80 characters, responsibilities at most "
        f"220 characters, and edge labels at most {spec.edge_label_chars} characters. Return only "
        "the schema-constrained object as compact JSON without indentation or line breaks.\n"
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


def _raise_topology(path: str) -> None:
    raise AppliedGraphSpecError(
        "graph_design_topology_invalid", path=path, rule="topology"
    )


def _normalise_parent_indexes(parent_indexes: list[int]) -> list[int]:
    zero_based = all(
        0 <= parent_index < component_index
        for component_index, parent_index in enumerate(parent_indexes, start=1)
    )
    if zero_based:
        return parent_indexes

    one_based = all(
        1 <= parent_index <= component_index
        for component_index, parent_index in enumerate(parent_indexes, start=1)
    )
    if one_based:
        logger.info("Normalized one-based applied graph parent indexes")
        return [parent_index - 1 for parent_index in parent_indexes]

    invalid_index = next(
        component_index
        for component_index, parent_index in enumerate(parent_indexes, start=1)
        if not 0 <= parent_index < component_index
    )
    _raise_topology(f"components[{invalid_index - 1}][0]")


def _validate_component(
    component: list[Any],
    *,
    node_index: int,
    field_offset: int,
    path: str,
    spec: AppliedGraphSpec,
) -> dict[str, Any]:
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
    }


def _validate_components(
    raw_root: Any,
    raw_components: list[Any],
    spec: AppliedGraphSpec,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[int]]:
    root = _required_tuple(raw_root, _ROOT_FIELD_COUNT, path="root")
    components = [
        _validate_component(
            root,
            node_index=0,
            field_offset=0,
            path="root",
            spec=spec,
        )
    ]
    group_indexes = [_required_index(root[3], path="root[3]")]
    tree_edges: list[dict[str, str]] = []
    component_rows = [
        _required_tuple(
            raw_component,
            _COMPONENT_FIELD_COUNT,
            path=f"components[{component_index - 1}]",
        )
        for component_index, raw_component in enumerate(raw_components, start=1)
    ]
    parent_indexes = _normalise_parent_indexes(
        [
            _required_index(component[0], path=f"components[{index}][0]")
            for index, component in enumerate(component_rows)
        ]
    )
    for component_index, (component, parent_index) in enumerate(
        zip(component_rows, parent_indexes, strict=True),
        start=1,
    ):
        path = f"components[{component_index - 1}]"
        components.append(
            _validate_component(
                component,
                node_index=component_index,
                field_offset=1,
                path=path,
                spec=spec,
            )
        )
        group_indexes.append(_required_index(component[4], path=f"{path}[4]"))
        tree_edges.append(
            {
                "source": f"n{parent_index + 1}",
                "target": f"n{component_index + 1}",
                "label": _required_text(
                    component[5], spec.edge_label_chars, path=f"{path}[5]"
                ),
                "flow": _coded_token(component[6], _FLOW_CODES, path=f"{path}[6]"),
                "sync": _coded_token(component[7], _SYNC_CODES, path=f"{path}[7]"),
            }
        )
    return components, tree_edges, group_indexes


def _validate_group_memberships(
    raw_groups: list[Any], group_indexes: list[int], spec: AppliedGraphSpec
) -> list[tuple[str, str]]:
    group_sources: dict[tuple[str, str], str] = {}
    groups: list[tuple[str, str]] = []
    for group_index, raw_group in enumerate(raw_groups):
        path = f"composition.groups[{group_index}]"
        group_record = _required_tuple(raw_group, _GROUP_FIELD_COUNT, path=path)
        full_group = _normalised_required_text(
            group_record[0], path=f"{path}[0]"
        )
        group = _bounded_text(
            full_group, spec.group_label_chars, path=f"{path}[0]"
        )
        group_kind = _coded_token(
            group_record[1], _GROUP_KIND_CODES, path=f"{path}[1]"
        )
        group_key = (group, group_kind)
        prior_group = group_sources.get(group_key)
        if prior_group is not None and prior_group != full_group:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid",
                path=f"{path}[0]",
                rule="bounded_identity_collision",
            )
        group_sources[group_key] = full_group
        groups.append(group_key)

    memberships: list[tuple[str, str]] = []
    for component_index, group_index in enumerate(group_indexes):
        path = (
            "root[3]"
            if component_index == 0
            else f"components[{component_index - 1}][4]"
        )
        if group_index < 0 or group_index >= len(groups):
            _raise_topology(path)
        memberships.append(groups[group_index])
    return memberships


def _validate_links(
    raw_links: list[Any],
    node_count: int,
    tree_edges: list[dict[str, str]],
    spec: AppliedGraphSpec,
) -> list[dict[str, str]]:
    edges = list(tree_edges)
    seen_edges = {
        (edge["source"], edge["target"], edge["label"].lower())
        for edge in tree_edges
    }
    for link_index, raw_edge in enumerate(raw_links):
        path = f"connections.links[{link_index}]"
        edge_record = _required_tuple(raw_edge, _LINK_FIELD_COUNT, path=path)
        source_index = _required_index(edge_record[0], path=f"{path}[0]")
        target_index = _required_index(edge_record[1], path=f"{path}[1]")
        if (
            source_index < 0
            or source_index >= node_count
            or target_index < 0
            or target_index >= node_count
            or source_index == target_index
        ):
            _raise_topology(path)
        edge = {
            "source": f"n{source_index + 1}",
            "target": f"n{target_index + 1}",
            "label": _required_text(
                edge_record[2], spec.edge_label_chars, path=f"{path}[2]"
            ),
            "flow": _coded_token(edge_record[3], _FLOW_CODES, path=f"{path}[3]"),
            "sync": _coded_token(
                edge_record[4], _SYNC_CODES, path=f"{path}[4]"
            ),
        }
        identity = (edge["source"], edge["target"], edge["label"].lower())
        if identity in seen_edges:
            raise AppliedGraphSpecError(
                "graph_design_topology_invalid", path=path, rule="duplicate"
            )
        seen_edges.add(identity)
        edges.append(edge)
    return edges


def _validate_sequence_steps(raw_steps: list[Any], tree_count: int) -> list[int]:
    sequence_steps = [0] * (tree_count + 1)
    seen_components: set[int] = set()
    for step_index, raw_step in enumerate(raw_steps):
        path = f"composition.steps[{step_index}]"
        if not isinstance(raw_step, list):
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="container_type"
            )
        if not raw_step:
            _raise_topology(path)
        for item_index, value in enumerate(raw_step):
            component_path = f"{path}[{item_index}]"
            component_index = _required_index(value, path=component_path)
            if component_index <= 0 or component_index > tree_count:
                _raise_topology(component_path)
            if component_index in seen_components:
                raise AppliedGraphSpecError(
                    "graph_design_topology_invalid",
                    path=component_path,
                    rule="duplicate",
                )
            seen_components.add(component_index)
            sequence_steps[component_index] = step_index + 1
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
        "groups",
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
    raw_groups = raw_composition["groups"]
    raw_steps = raw_composition["steps"]
    for value, path in (
        (raw_links, "connections.links"),
        (raw_groups, "composition.groups"),
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
    components, tree_edges, group_indexes = _validate_components(
        raw_root, raw_components, spec
    )
    memberships = _validate_group_memberships(raw_groups, group_indexes, spec)
    sequence_steps = _validate_sequence_steps(raw_steps, len(raw_components))
    nodes = [
        {
            **component,
            "group": group,
            "group_kind": group_kind,
            "tier": None,
            "lane": "bottom" if group_kind == "operations" else "main",
            "sequence_step": sequence_step,
        }
        for component, (group, group_kind), sequence_step in zip(
            components, memberships, sequence_steps, strict=True
        )
    ]
    edges = _validate_links(raw_links, node_count, tree_edges, spec)

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
    node_count = max(0, spec.safety_max_nodes)
    root = [
        "l" * spec.node_label_chars,
        max(_NODE_TYPE_CODES),
        "r" * spec.responsibility_chars,
        0,
    ]
    components = [
        [
            index,
            "l" * spec.node_label_chars,
            max(_NODE_TYPE_CODES),
            "r" * spec.responsibility_chars,
            index + 1,
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
    groups = [
        [
            f"{index:02d}" + "g" * max(0, spec.group_label_chars - 2),
            max(_GROUP_KIND_CODES),
        ]
        for index in range(node_count)
    ]
    payload = {
        "root": root,
        "components": components,
        "connections": {"links": links},
        "composition": {
            "title": "t" * spec.title_chars,
            "groups": groups,
            "steps": [[index] for index in range(1, len(components) + 1)],
        },
    }
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
