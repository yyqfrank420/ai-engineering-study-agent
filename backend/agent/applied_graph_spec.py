from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
import json
import logging
from typing import Any

from agent.state import GraphData


_GLOBAL_NODE_CAP = 13
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
_NODE_SLOT_COUNT = 9
_MAX_CROSS_LINK_SLOTS = 10
_ROOT_PARENT = "ROOT"

logger = logging.getLogger(__name__)

_ERROR_RULES = frozenset({
    "blank_required",
    "container_type",
    "invalid_enum",
    "invalid_slot",
    "json_decode",
    "key_set",
    "provider_finish",
    "semantic_roles",
    "value_type",
})
_NORMALIZATION_RULES = frozenset({
    "blank_optional",
    "blank_text",
    "cycle",
    "depth",
    "duplicate",
    "invalid_endpoint",
    "invalid_parent",
    "link_budget",
    "root_metadata",
    "root_parent",
    "self_loop",
    "self_parent",
    "token_canonicalized",
    "truncated",
})
_NORMALIZATION_ACTIONS = frozenset({
    "canonicalized", "defaulted", "dropped", "ignored", "reparented", "truncated",
})
_MUTATION_ROLE_ORDER = ("validator", "approver", "executor", "authoritative_state")
_MUTATION_ROLE_KEYWORDS = {
    "validator": frozenset({
        "validate", "validation", "validator", "verify", "verification", "verifier",
        "guard", "interlock", "safety", "schema", "policy", "check",
    }),
    "approver": frozenset({
        "approve", "approval", "approver", "authorize", "authorization", "review",
        "gate", "signoff",
    }),
    "executor": frozenset({
        "execute", "execution", "executor", "adapter", "sender", "dispatcher", "writer",
        "delivery", "deploy", "deployment", "publisher",
    }),
    "authoritative_state": frozenset({
        "authoritative", "canonical", "ledger", "state", "store", "registry", "database",
        "record", "source",
    }),
}
_MUTATION_ROLE_TYPE_SCORES = {
    "validator": {"control": 30, "decision": 25, "gateway": 15, "service": 5},
    "approver": {"decision": 30, "control": 25, "gateway": 10, "service": 5},
    "executor": {"service": 30, "gateway": 25, "external": 20, "control": 5},
    "authoritative_state": {"datastore": 30, "external": 25, "control": 10},
}
_MUTATION_ROLE_PRESERVATION_BONUS = 10_000


@dataclass(frozen=True)
class AppliedGraphSpec:
    depth: str
    min_nodes: int
    target_nodes: int
    max_nodes: int
    max_edges: int
    max_groups: int = 4
    max_sequence_steps: int = 5
    max_assumptions: int = 3
    title_chars: int = 100
    id_chars: int = 80
    node_label_chars: int = 60
    responsibility_chars: int = 220
    edge_label_chars: int = 100
    assumption_chars: int = 160
    query_chars: int = 2000
    projected_item_chars: int = 280
    max_output_tokens: int = 3600


_SPECS = {
    "prototype": AppliedGraphSpec(
        depth="prototype",
        min_nodes=7,
        target_nodes=9,
        max_nodes=12,
        max_edges=27,
        max_output_tokens=5200,
    ),
    "production": AppliedGraphSpec(
        depth="production",
        min_nodes=9,
        target_nodes=9,
        max_nodes=_GLOBAL_NODE_CAP,
        max_edges=30,
        max_output_tokens=5200,
    ),
}


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


def _record_normalization(path: str, rule: str, action: str) -> None:
    if rule not in _NORMALIZATION_RULES or action not in _NORMALIZATION_ACTIONS:
        return
    safe_path = path[:96]
    if not safe_path or not all(
        char.isascii() and (char.isalnum() or char in "_$.[ ]")
        for char in safe_path
    ):
        return
    logger.info(
        "Applied topology field normalized",
        extra={
            "graph_normalization_path": safe_path,
            "graph_normalization_rule": rule,
            "graph_normalization_action": action,
        },
    )


def _record_mutation_role(
    role: str,
    category: str,
    *,
    score: int,
    preservation_count: int,
) -> None:
    if role not in _MUTATION_ROLE_ORDER or category not in {
        "inactive_clear", "inferred", "preserved", "reassigned",
    }:
        return
    logger.info(
        "Applied topology mutation role normalized",
        extra={
            "graph_mutation_role": role,
            "graph_mutation_category": category,
            "graph_mutation_score": max(0, min(int(score), 100_000)),
            "graph_mutation_preservation_count": max(
                0, min(int(preservation_count), len(_MUTATION_ROLE_ORDER))
            ),
        },
    )


def applied_graph_spec(depth: str) -> AppliedGraphSpec:
    return _SPECS["production" if depth == "production" else "prototype"]


def _node_slots() -> tuple[str, ...]:
    return tuple(f"n{index}" for index in range(1, _NODE_SLOT_COUNT + 1))


def _parent_slots(index: int) -> tuple[str, ...]:
    """Admit any non-self fixed slot; topology repair establishes the rooted tree."""
    if index == 1:
        return (_ROOT_PARENT,)
    node_id = f"n{index}"
    return tuple(slot for slot in _node_slots() if slot != node_id)


def applied_graph_topology_schema(spec: AppliedGraphSpec) -> dict[str, Any]:
    node_slots = _node_slots()
    node_required = [
        "label", "type", "tier", "lane", "responsibility",
        "parent", "parent_label", "parent_flow", "parent_sync",
    ]
    node_record = {
        "type": "object",
        "additionalProperties": False,
        "required": node_required,
        "properties": {
            "label": {"type": "string"},
            "type": {"type": "string", "enum": list(_NODE_TYPES)},
            "tier": {"type": "string", "enum": list(_TIERS)},
            "lane": {"type": "string", "enum": list(_LANES)},
            "responsibility": {"type": "string"},
            "parent": {"type": "string", "enum": [_ROOT_PARENT, *node_slots]},
            "parent_label": {"type": "string"},
            "parent_flow": {"type": "string", "enum": list(_FLOWS)},
            "parent_sync": {"type": "string", "enum": list(_SYNC_MODES)},
        },
    }
    cross_link_record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "target", "label", "flow", "sync"],
        "properties": {
            "source": {"type": "string", "enum": list(node_slots)},
            "target": {"type": "string", "enum": list(node_slots)},
            "label": {"type": "string"},
            "flow": {"type": "string", "enum": list(_FLOWS)},
            "sync": {"type": "string", "enum": list(_SYNC_MODES)},
        },
    }
    mutation_control = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "external_mutation",
            "validator",
            "approver",
            "executor",
            "authoritative_state",
        ],
        "properties": {
            "external_mutation": {"type": "boolean"},
            "validator": {"type": "string"},
            "approver": {"type": "string"},
            "executor": {"type": "string"},
            "authoritative_state": {"type": "string"},
        },
    }
    return {
        "$defs": {
            "node_record": node_record,
            "cross_link_record": cross_link_record,
        },
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "nodes", "cross_links", "mutation_control"],
        "properties": {
            "title": {"type": "string"},
            "nodes": {
                "type": "object",
                "additionalProperties": False,
                "required": list(node_slots),
                "properties": {
                    slot: {"$ref": "#/$defs/node_record"} for slot in node_slots
                },
            },
            "cross_links": {
                "type": "array",
                "items": {"$ref": "#/$defs/cross_link_record"},
            },
            "mutation_control": mutation_control,
        },
    }


def _bounded_text(value: Any, limit: int) -> str:
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:limit]


def _collect_projection_items(
    value: Any,
    needles: tuple[str, ...],
    *,
    item_limit: int,
    char_limit: int,
) -> list[str]:
    collected: list[str] = []

    def visit(current: Any, matched: bool = False) -> None:
        if len(collected) >= item_limit:
            return
        if isinstance(current, dict):
            for key, child in current.items():
                key_matches = any(needle in str(key).lower() for needle in needles)
                visit(child, matched or key_matches)
            return
        if isinstance(current, list):
            for child in current:
                visit(child, matched)
            return
        if matched and current not in (None, ""):
            text = _bounded_text(current, char_limit)
            if text and text not in collected:
                collected.append(text)

    visit(value)
    return collected[:item_limit]


def project_architect_plan(plan: Any, spec: AppliedGraphSpec) -> dict[str, list[str]]:
    return {
        "components": _collect_projection_items(
            plan, ("component", "responsibil", "actor"), item_limit=16,
            char_limit=spec.projected_item_chars,
        ),
        "branches": _collect_projection_items(
            plan, ("branch", "route", "flow", "rejoin"), item_limit=10,
            char_limit=spec.projected_item_chars,
        ),
        "decisions": _collect_projection_items(
            plan, ("decision", "approval", "policy", "gate"), item_limit=10,
            char_limit=spec.projected_item_chars,
        ),
        "failures": _collect_projection_items(
            plan, ("failure", "timeout", "rollback", "degrad"), item_limit=10,
            char_limit=spec.projected_item_chars,
        ),
        "assumptions": _collect_projection_items(
            plan, ("assumption", "constraint", "open_question"),
            item_limit=spec.max_assumptions,
            char_limit=spec.assumption_chars,
        ),
    }


def project_challenger_blockers(review: Any, spec: AppliedGraphSpec) -> list[str]:
    return _collect_projection_items(
        review,
        ("block", "missing", "risk", "failure", "advice"),
        item_limit=6,
        char_limit=spec.projected_item_chars,
    )


def applied_graph_topology_prompt(
    *,
    query: str,
    architect_plan: Any,
    challenger_review: Any,
    commitments: str,
    spec: AppliedGraphSpec,
) -> str:
    projection = {
        "request": _bounded_text(query, spec.query_chars),
        "depth": spec.depth,
        "node_budget": {
            "exact": _NODE_SLOT_COUNT,
            "slots": list(_node_slots()),
        },
        "cross_link_budget": _MAX_CROSS_LINK_SLOTS,
        "edge_max_after_enrichment": spec.max_edges,
        "authoring_limits": {
            "title_chars": 100,
            "node_label_chars": 60,
            "responsibility_chars": 140,
            "responsibility_sentences": 1,
            "parent_or_cross_link_label_chars": 80,
        },
        "architect": project_architect_plan(architect_plan, spec),
        "challenger_blockers": project_challenger_blockers(challenger_review, spec),
        "diagram_commitments": _bounded_text(commitments, 3600),
    }
    return (
        "Build the compact topology from this normalized design input. Return every fixed node "
        "slot n1 through n9 exactly once. n1 uses parent ROOT; every other slot selects one schema-"
        "allowed non-self fixed-slot parent and authors the label, flow, and sync for that parent edge. Keep "
        "the title at most 100 characters and every node label at most 60 characters. Write each "
        "responsibility as one sentence of at most 140 characters and every parent or cross-link "
        "label at most 80 characters. Put no prose outside the schema fields. Keep parent depth at "
        "or below five. A slot's label and responsibility are its semantic identity; "
        "keep that identity stable in every link and later expansion. Return cross_links as an "
        "array with at most ten distinct material non-tree links; include material cross-links only. "
        "Preserve material branch/rejoin, "
        "trust-boundary, approval/rejection, accepted-only cache, and rollback topology within the "
        "hard maximum. Every approval decision needs distinct approved and rejected outbound routes. "
        "Rejection is a no-effect outcome, never compensation. When an action can fail after an "
        "effect or produce a late anomaly, add a separate bounded compensation route that re-enters "
        "the same proposal, policy, approval, and execution controls. Give every budget or retry "
        "exhaustion path its own explicit terminal edge, never combined with success. Keep "
        "COMMITTED, NOT_FOUND retry, and "
        "STILL_UNKNOWN escalation distinct when reconciliation applies; keep canary, full promotion, "
        "and rollback as distinct edges when release applies. Every edge label must state the complete "
        "visible action or control contract; never use a self-loop. The parent links must form a "
        "rooted, acyclic n1 tree before cross-links. Set mutation_control.external_mutation "
        "true whenever any path can change an external or authoritative system, then identify four "
        "distinct fixed slot IDs from n1 through n9 for its validator, approver, executor, and "
        "authoritative state. These required role IDs are semantic hints normalized server-side; "
        "the visible topology must still prove the control contract. "
        "Set it false with four empty IDs only for a genuinely no-external-effect design. Return only "
        "the schema-constrained object.\n"
        + json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
    )


def _bounded_field(
    value: Any,
    limit: int,
    *,
    path: str,
    default: str | None = None,
    drop_blank: bool = False,
) -> str | None:
    if not isinstance(value, str):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type",
        )
    normalized = " ".join(value.split())
    if not normalized:
        if drop_blank:
            _record_normalization(path, "blank_optional", "dropped")
            return None
        if default is None:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="blank_required",
            )
        _record_normalization(path, "blank_text", "defaulted")
        normalized = default
    if len(normalized) > limit:
        _record_normalization(path, "truncated", "truncated")
    return normalized[:limit]


def _canonical_token(
    value: Any,
    allowed: tuple[str, ...],
    *,
    path: str,
    invalid_is_none: bool = False,
) -> str | None:
    if not isinstance(value, str):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="value_type",
        )
    stripped = value.strip()
    canonical = None
    if stripped.isascii():
        by_lower = {token.lower(): token for token in allowed}
        canonical = by_lower.get(stripped.lower())
    if canonical is None:
        if invalid_is_none:
            return None
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path=path, rule="invalid_enum",
        )
    if value != canonical:
        _record_normalization(path, "token_canonicalized", "canonicalized")
    return canonical


def _semantic_tokens(value: str) -> frozenset[str]:
    normalized = "".join(
        char.lower() if char.isascii() and char.isalnum() else " "
        for char in value
    )
    return frozenset(normalized.split())


def _mutation_role_semantic_score(role: str, node: dict[str, str]) -> int:
    keywords = _MUTATION_ROLE_KEYWORDS[role]
    label_hits = len(_semantic_tokens(node["label"]) & keywords)
    responsibility_hits = len(_semantic_tokens(node["responsibility"]) & keywords)
    return (
        (100 * label_hits)
        + (50 * responsibility_hits)
        + _MUTATION_ROLE_TYPE_SCORES[role].get(node["type"], 0)
    )


def _assign_mutation_roles(
    nodes: list[dict[str, str]],
    provided: dict[str, str | None],
) -> dict[str, str]:
    nodes_by_id = {node["id"]: node for node in nodes}
    slot_order = {node_id: index for index, node_id in enumerate(_node_slots(), start=1)}
    best_assignment: tuple[str, ...] | None = None
    best_role_scores: tuple[int, ...] | None = None
    best_key: tuple[Any, ...] | None = None
    for assignment in permutations(_node_slots(), len(_MUTATION_ROLE_ORDER)):
        role_scores = tuple(
            _mutation_role_semantic_score(role, nodes_by_id[node_id])
            + (
                _MUTATION_ROLE_PRESERVATION_BONUS
                if provided.get(role) == node_id
                else 0
            )
            for role, node_id in zip(_MUTATION_ROLE_ORDER, assignment)
        )
        preservation_count = sum(
            provided.get(role) == node_id
            for role, node_id in zip(_MUTATION_ROLE_ORDER, assignment)
        )
        key = (
            sum(role_scores),
            preservation_count,
            role_scores,
            tuple(-slot_order[node_id] for node_id in assignment),
        )
        if best_key is None or key > best_key:
            best_key = key
            best_assignment = assignment
            best_role_scores = role_scores
    assert best_assignment is not None and best_role_scores is not None
    preservation_count = sum(
        provided.get(role) == node_id
        for role, node_id in zip(_MUTATION_ROLE_ORDER, best_assignment)
    )
    assigned = dict(zip(_MUTATION_ROLE_ORDER, best_assignment))
    for role, node_id, score in zip(
        _MUTATION_ROLE_ORDER, best_assignment, best_role_scores
    ):
        if provided.get(role) == node_id:
            category = "preserved"
        elif provided.get(role) is not None:
            category = "reassigned"
        else:
            category = "inferred"
        _record_mutation_role(
            role,
            category,
            score=score,
            preservation_count=preservation_count,
        )
    return assigned


def validate_applied_graph_topology(
    payload: Any,
    spec: AppliedGraphSpec,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "title", "nodes", "cross_links", "mutation_control",
    }:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="$", rule="key_set",
        )
    title = _bounded_field(
        payload.get("title"), spec.title_chars, path="title",
        default="Applied Agent Architecture",
    )
    assert title is not None
    raw_nodes = payload.get("nodes")
    cross_links = payload.get("cross_links")
    node_slots = _node_slots()
    if not isinstance(raw_nodes, dict) or set(raw_nodes) != set(node_slots):
        raise AppliedGraphSpecError("graph_design_node_budget_invalid")
    if not isinstance(cross_links, list):
        raise AppliedGraphSpecError(
            "graph_design_edge_budget_invalid",
            node_count=len(node_slots),
        )
    normalized_nodes: list[dict[str, str]] = []
    normalized_edges: list[dict[str, str]] = []
    parents: dict[str, str] = {}
    parent_edge_metadata: dict[str, dict[str, str]] = {}
    node_keys = {
        "label", "type", "tier", "lane", "responsibility",
        "parent", "parent_label", "parent_flow", "parent_sync",
    }
    for index, node_id in enumerate(node_slots, start=1):
        node = raw_nodes[node_id]
        if not isinstance(node, dict) or set(node) != node_keys:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=f"nodes.{node_id}", rule="key_set",
            )
        node_type = _canonical_token(
            node.get("type"), _NODE_TYPES, path=f"nodes.{node_id}.type",
        )
        tier = _canonical_token(
            node.get("tier"), _TIERS, path=f"nodes.{node_id}.tier",
        )
        lane = _canonical_token(
            node.get("lane"), _LANES, path=f"nodes.{node_id}.lane",
        )
        parent = _canonical_token(
            node.get("parent"), (_ROOT_PARENT, *node_slots),
            path=f"nodes.{node_id}.parent", invalid_is_none=True,
        )
        parent_flow = _canonical_token(
            node.get("parent_flow"), _FLOWS,
            path=f"nodes.{node_id}.parent_flow",
        )
        parent_sync = _canonical_token(
            node.get("parent_sync"), _SYNC_MODES,
            path=f"nodes.{node_id}.parent_sync",
        )
        assert node_type is not None and tier is not None and lane is not None
        assert parent_flow is not None and parent_sync is not None
        label = _bounded_field(
            node.get("label"), spec.node_label_chars,
            path=f"nodes.{node_id}.label",
            default=f"{node_type.title()} {node_id}",
        )
        responsibility = _bounded_field(
            node.get("responsibility"), spec.responsibility_chars,
            path=f"nodes.{node_id}.responsibility",
            default=f"Handles the assigned {node_type} responsibility.",
        )
        assert label is not None and responsibility is not None
        if index == 1:
            parents[node_id] = _ROOT_PARENT
            if parent != _ROOT_PARENT:
                _record_normalization(
                    f"nodes.{node_id}.parent", "root_parent", "reparented",
                )
        else:
            if parent is None:
                parents[node_id] = "n1"
                _record_normalization(
                    f"nodes.{node_id}.parent", "invalid_parent", "reparented",
                )
            elif parent == _ROOT_PARENT:
                parents[node_id] = "n1"
                _record_normalization(
                    f"nodes.{node_id}.parent", "root_parent", "reparented",
                )
            elif parent == node_id:
                parents[node_id] = "n1"
                _record_normalization(
                    f"nodes.{node_id}.parent", "self_parent", "reparented",
                )
            else:
                parents[node_id] = parent
        parent_label_path = f"nodes.{node_id}.parent_label"
        if index == 1:
            if not isinstance(node.get("parent_label"), str):
                raise AppliedGraphSpecError(
                    "graph_design_schema_invalid", path=parent_label_path,
                    rule="value_type",
                )
            _record_normalization(parent_label_path, "root_metadata", "ignored")
            parent_label = ""
        else:
            parent_label = _bounded_field(
                node.get("parent_label"), spec.edge_label_chars,
                path=parent_label_path,
                default=f"Routes validated work to {label}",
            )
            assert parent_label is not None
        parent_edge_metadata[node_id] = {
            "label": parent_label,
            "flow": parent_flow,
            "sync": parent_sync,
        }
        normalized_nodes.append({
            "id": node_id,
            "label": label,
            "type": node_type,
            "tier": tier,
            "lane": lane,
            "responsibility": responsibility,
        })
    slot_order = {node_id: index for index, node_id in enumerate(node_slots)}
    while True:
        cycle: list[str] | None = None
        for start in node_slots[1:]:
            path: list[str] = []
            positions: dict[str, int] = {}
            current = start
            while current != "n1":
                if current in positions:
                    cycle = path[positions[current]:]
                    break
                positions[current] = len(path)
                path.append(current)
                current = parents[current]
            if cycle is not None:
                break
        if cycle is None:
            break
        repaired = min(cycle, key=slot_order.__getitem__)
        parents[repaired] = "n1"
        _record_normalization(f"nodes.{repaired}.parent", "cycle", "reparented")
    for node_id in node_slots[1:]:
        depth = 0
        current = node_id
        while current != "n1":
            current = parents[current]
            depth += 1
        if depth > 5:
            parents[node_id] = "n1"
            _record_normalization(f"nodes.{node_id}.parent", "depth", "reparented")
    for node_id in node_slots[1:]:
        metadata = parent_edge_metadata[node_id]
        normalized_edges.append({
            "source": parents[node_id],
            "target": node_id,
            "label": metadata["label"],
            "flow": metadata["flow"],
            "sync": metadata["sync"],
        })
    seen_edges = {
        (edge["source"], edge["target"], edge["label"].lower())
        for edge in normalized_edges
    }
    accepted_cross_links = 0
    edge_keys = {"source", "target", "label", "flow", "sync"}
    for edge_index, edge in enumerate(cross_links):
        edge_path = f"cross_links[{edge_index}]"
        if not isinstance(edge, dict) or set(edge) != edge_keys:
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=edge_path, rule="key_set",
            )
        source = _canonical_token(
            edge.get("source"), node_slots, path=f"{edge_path}.source",
            invalid_is_none=True,
        )
        target = _canonical_token(
            edge.get("target"), node_slots, path=f"{edge_path}.target",
            invalid_is_none=True,
        )
        flow = _canonical_token(
            edge.get("flow"), _FLOWS, path=f"{edge_path}.flow",
        )
        sync = _canonical_token(
            edge.get("sync"), _SYNC_MODES, path=f"{edge_path}.sync",
        )
        label = _bounded_field(
            edge.get("label"), spec.edge_label_chars,
            path=f"{edge_path}.label", drop_blank=True,
        )
        assert flow is not None and sync is not None
        if source is None or target is None:
            _record_normalization(edge_path, "invalid_endpoint", "dropped")
            continue
        if label is None:
            continue
        if source == target:
            _record_normalization(edge_path, "self_loop", "dropped")
            continue
        edge_key = (source, target, label.lower())
        if edge_key in seen_edges:
            _record_normalization(edge_path, "duplicate", "dropped")
            continue
        if accepted_cross_links >= _MAX_CROSS_LINK_SLOTS:
            _record_normalization(edge_path, "link_budget", "ignored")
            continue
        accepted_cross_links += 1
        seen_edges.add(edge_key)
        normalized_edges.append({
            "source": source,
            "target": target,
            "label": label,
            "flow": flow,
            "sync": sync,
        })
    if len(normalized_edges) > spec.max_edges:
        raise AppliedGraphSpecError(
            "graph_design_edge_budget_invalid",
            node_count=len(node_slots), edge_count=len(normalized_edges),
        )
    mutation_control = payload.get("mutation_control")
    control_keys = {
        "external_mutation", "validator", "approver", "executor", "authoritative_state",
    }
    if not isinstance(mutation_control, dict) or set(mutation_control) != control_keys:
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="mutation_control", rule="key_set",
        )
    external_mutation = mutation_control.get("external_mutation")
    if not isinstance(external_mutation, bool):
        raise AppliedGraphSpecError(
            "graph_design_schema_invalid", path="mutation_control.external_mutation",
            rule="value_type",
        )
    raw_roles: dict[str, str] = {}
    for key in _MUTATION_ROLE_ORDER:
        value = mutation_control.get(key)
        path = f"mutation_control.{key}"
        if not isinstance(value, str):
            raise AppliedGraphSpecError(
                "graph_design_schema_invalid", path=path, rule="value_type",
            )
        raw_roles[key] = value
    if not external_mutation:
        role_ids = {role: "" for role in _MUTATION_ROLE_ORDER}
        for role, value in raw_roles.items():
            if value:
                _record_mutation_role(
                    role, "inactive_clear", score=0, preservation_count=0,
                )
    else:
        provided = {
            role: _canonical_token(
                value,
                node_slots,
                path=f"mutation_control.{role}",
                invalid_is_none=True,
            )
            for role, value in raw_roles.items()
        }
        role_ids = _assign_mutation_roles(normalized_nodes, provided)
        if (
            any(value not in node_slots for value in role_ids.values())
            or len(set(role_ids.values())) != len(_MUTATION_ROLE_ORDER)
        ):
            raise AppliedGraphSpecError(
                "graph_design_mutation_control_invalid",
                path="mutation_control", rule="semantic_roles",
            )
    return {
        "title": title,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "mutation_control": {
            "external_mutation": external_mutation,
            **role_ids,
        },
    }


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
    mutation_control = draft["mutation_control"]
    if mutation_control["external_mutation"]:
        validator_id = mutation_control["validator"]
        authoritative_state_id = mutation_control["authoritative_state"]
        has_compensation_reentry = any(
            edge["source"] == authoritative_state_id
            and edge["target"] == validator_id
            and "compensat" in str(edge["label"]).lower()
            for edge in edges
        )
        if not has_compensation_reentry:
            if len(edges) >= spec.max_edges:
                raise AppliedGraphSpecError(
                    "graph_design_edge_budget_invalid",
                    node_count=len(nodes),
                    edge_count=len(edges) + 1,
                )
            label = (
                "Late anomaly creates a new typed compensation proposal with a new operation "
                "identity; never retry the original"
            )
            edges.append({
                "source": authoritative_state_id,
                "target": validator_id,
                "label": label,
                "technology": applied_graph_edge_technology("control"),
                "sync": "async",
                "description": label,
                "flow": "control",
            })
    node_ids = [node["id"] for node in draft["nodes"]]
    groups = [
        {"id": "runtime", "label": "Runtime", "kind": "runtime", "nodeIds": node_ids[:3]},
        {"id": "control_data", "label": "Control and Data", "kind": "data", "nodeIds": node_ids[3:6]},
        {"id": "delivery_operations", "label": "Delivery and Operations", "kind": "operations", "nodeIds": node_ids[6:]},
    ][:spec.max_groups]
    sequence_edges = list(draft["edges"])
    sequence = [
        {
            "step": index,
            "nodes": [edge["source"], edge["target"]],
            "description": edge["label"],
        }
        for index, edge in enumerate(
            sequence_edges[:spec.max_sequence_steps], start=1
        )
    ]
    assumptions = project_architect_plan(architect_plan, spec)["assumptions"]
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
    node_ids = list(_node_slots())
    payload = {
        "title": "t" * spec.title_chars,
        "nodes": {
            node_id: {
                "label": "l" * spec.node_label_chars,
                "type": "service",
                "tier": "private",
                "lane": "main",
                "responsibility": "r" * spec.responsibility_chars,
                "parent": _ROOT_PARENT if index == 1 else "n1",
                "parent_label": "e" * spec.edge_label_chars,
                "parent_flow": "runtime",
                "parent_sync": "sync",
            }
            for index, node_id in enumerate(node_ids, start=1)
        },
        "cross_links": [
            {
                "source": node_ids[index % len(node_ids)],
                "target": node_ids[(index + 1) % len(node_ids)],
                "label": "e" * spec.edge_label_chars,
                "flow": "runtime",
                "sync": "sync",
            }
            for index in range(_MAX_CROSS_LINK_SLOTS)
        ],
        "mutation_control": {
            "external_mutation": False,
            "validator": "",
            "approver": "",
            "executor": "",
            "authoritative_state": "",
        },
    }
    return len(json.dumps(payload, separators=(",", ":")))
