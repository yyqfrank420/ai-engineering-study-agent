import json
import logging
import re
import time
from copy import deepcopy
from typing import Any

from adapters.llm_adapter import build_telemetry
from agent.architecture_playbook import format_evidence_bundle
from agent.complexity import resolve_complexity
from agent.deadlines import critic_timeout_seconds as _configured_critic_timeout_seconds
from agent.graph_repair_contract import (
    APPROVAL_SCORE as _APPROVAL_SCORE,
    COMPOSITION_FIELDS as _COMPOSITION_FIELDS,
    REPAIR_LAYERS as _REPAIR_LAYERS,
    validate_repair_contract as _validate_repair_contract,
)
from agent.state import AgentState
from agent.stream_utils import StructuredLLMResponse, stream_structured_llm
from config import settings


logger = logging.getLogger(__name__)

_GRAPH_CRITIC_PROMPT_VERSION = "architecture_critic_v34"
# Sonnet 5 high effort can spend the full output allowance on adaptive thinking
# before emitting the required scorecard. Medium keeps the review inside one call.
_GRAPH_CRITIC_EFFORT = "medium"
_GRAPH_STAGE_DEADLINE_KEY = "_graph_stage_deadline_s"
_GRAPH_STAGE_FINALIZATION_HEADROOM_S = 1.0
_TOPOLOGY_PROOF_GUARANTEES = {
    "state_effect_reconciliation",
    "authorization_and_compensation",
    "retrieval_and_reuse_trust",
    "audit_and_provenance",
    "learning_and_release",
}
_GRAPH_CRITIC_COMPACT_PROTOCOL = """

Response-size contract:
- Return only the fixed JSON scorecard; do not restate the request, graph, checklist, or reasoning.
- Use each rubric finding code at most once per layer. Select records by their zero-based positions
  in the candidate nodes, edges, groups, sequence, and assumptions arrays.
- If a repair changes several artifact types, fail each owning layer with its own finding code and
  indexes. Cite the smallest witness subgraph and directed endpoint claims for each topology
  guarantee.
- Passing layers have empty finding and selector arrays. Preserve every required layer and proof.
"""


def _strict_object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


_RUBRIC_CODES = (
    "domain_specificity",
    "objective_fidelity",
    "runtime_completeness",
    "safe_action_boundary",
    "edge_semantics",
    "assumption_hygiene",
    "selected_depth",
    "novice_clarity",
    "logical_flow",
    "succinctness",
    "mece_scope",
    "authored_composition",
    "brief_coverage",
    "branch_completion",
    "independent_risk_coverage",
    "gate_preserving_reuse",
    "topology_enforced_guarantees",
    "controlled_external_effects",
    "race_and_ambiguity_safety",
    "canonical_state_and_trust",
    "controlled_learning_and_release",
    "safe_factual_failure",
    "pre_effect_durability_and_freshness",
    "complete_reconciliation",
    "complete_trust_and_release_scope",
    "state_order_integrity",
    "streaming_integrity",
)
_RUBRIC_CODE_OWNERS = {
    "domain_specificity": "components",
    "objective_fidelity": "components",
    "runtime_completeness": "connections",
    "safe_action_boundary": "connections",
    "edge_semantics": "connections",
    "assumption_hygiene": "composition",
    "selected_depth": "components",
    "novice_clarity": "render",
    "logical_flow": "connections",
    "succinctness": "components",
    "mece_scope": "components",
    "authored_composition": "composition",
    "brief_coverage": "components",
    "branch_completion": "connections",
    "independent_risk_coverage": "components",
    "gate_preserving_reuse": "connections",
    "topology_enforced_guarantees": "connections",
    "controlled_external_effects": "connections",
    "race_and_ambiguity_safety": "connections",
    "canonical_state_and_trust": "connections",
    "controlled_learning_and_release": "connections",
    "safe_factual_failure": "connections",
    "pre_effect_durability_and_freshness": "connections",
    "complete_reconciliation": "connections",
    "complete_trust_and_release_scope": "connections",
    "state_order_integrity": "connections",
    "streaming_integrity": "connections",
}
_RUBRIC_CODEBOOK = ", ".join(
    f"{index}={name}[{_RUBRIC_CODE_OWNERS[name]}]"
    for index, name in enumerate(_RUBRIC_CODES, start=1)
)

_MODEL_LAYER_FIELDS = {
    "components": (
        "status",
        "score",
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "node_indexes",
    ),
    "connections": (
        "status",
        "score",
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "edge_indexes",
    ),
    "composition": (
        "status",
        "score",
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "group_indexes",
        "composition_fields",
        "sequence_indexes",
        "assumption_indexes",
    ),
    "render": (
        "status",
        "score",
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
    ),
}
_MODEL_PROOF_FIELDS = ("status", "edge_indexes", "route_pairs")
_MODEL_LAYER_OUTPUT_EXAMPLE = ",\n".join(
    "    "
    + json.dumps(layer, ensure_ascii=False)
    + ": "
    + json.dumps(
        [
            "pass|fail" if field == "status" else 0.0 if field == "score" else []
            for field in fields
        ],
        ensure_ascii=False,
    )
    for layer, fields in _MODEL_LAYER_FIELDS.items()
)
_MODEL_LAYER_FIELD_LEGEND = "\n".join(
    f"- {layer}: {', '.join(fields)}."
    for layer, fields in _MODEL_LAYER_FIELDS.items()
)

# Anthropic compiles response schemas into a grammar. Repeating the full object schema for
# every named layer exceeds that compiler's size limit. The named MECE boundary stays explicit;
# shared tuple rows keep the provider grammar small. Python validates each field below.
_MODEL_LAYER_ROW_SCHEMA = {
    "type": "array",
    "items": {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {
                "type": "array",
                "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            },
        ]
    },
}
_MODEL_PROOF_ROW_SCHEMA = {
    "type": "array",
    "items": {
        "anyOf": [
            {"type": "string"},
            {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "integer"},
                        {"type": "array", "items": {"type": "integer"}},
                    ]
                },
            },
        ]
    },
}

_GRAPH_CRITIC_RESPONSE_SCHEMA = {
    **_strict_object_schema(
        {
            "repair_scope": {
                "type": "string",
                "enum": ["none", "local", "global"],
            },
            "layers": _strict_object_schema(
                {
                    layer: {"$ref": "#/$defs/layer_row"}
                    for layer in _MODEL_LAYER_FIELDS
                }
            ),
            "topology_proofs": _strict_object_schema(
                {
                    guarantee: {"$ref": "#/$defs/proof_row"}
                    for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
                }
            ),
        }
    ),
    "$defs": {
        "layer_row": _MODEL_LAYER_ROW_SCHEMA,
        "proof_row": _MODEL_PROOF_ROW_SCHEMA,
    },
}

_RENDER_REPORT_FIELDS = (
    "viewport_width",
    "viewport_height",
    "rendered_nodes",
    "rendered_edges",
    "overlap_count",
    "clipped_nodes",
    "clipped_edges",
    "minimum_text_px",
    "overview_required_edge_labels",
    "visible_overview_required_edge_labels",
    "grouped_nodes",
    "group_labelled_nodes",
    "visible_group_boundaries",
    "group_boundary_overlap_count",
    "capture_error",
)


def _project_records(value: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    records = value if isinstance(value, list) else []
    return [
        {field: item[field] for field in fields if field in item}
        for item in records
        if isinstance(item, dict)
    ]


def _semantic_graph_projection(graph: dict[str, Any]) -> dict[str, Any]:
    """Keep authored semantics and exact topology selectors, without render metadata."""
    return {
        "title": graph.get("title"),
        "nodes": _project_records(
            graph.get("nodes"),
            ("id", "label", "type", "description"),
        ),
        "edges": _project_records(
            graph.get("edges"),
            ("source", "target", "label", "flow", "sync"),
        ),
        "groups": _project_records(
            graph.get("groups"),
            ("id", "label", "kind", "nodeIds"),
        ),
        "sequence": _project_records(
            graph.get("sequence"),
            ("step", "nodes", "description"),
        ),
        "assumptions": [
            item
            for item in (graph.get("assumptions") or [])
            if isinstance(item, str)
        ],
    }


def _challenger_concerns(value: Any) -> dict[str, Any]:
    review = value if isinstance(value, dict) else {}
    return {
        "risks": _project_records(
            review.get("risks"),
            ("area", "risk", "mitigation"),
        ),
        "missing_requirements": [
            item
            for item in (review.get("missing_requirements") or [])
            if isinstance(item, str)
        ],
        "tradeoffs": [
            item
            for item in (review.get("tradeoffs") or [])
            if isinstance(item, str)
        ],
    }


def _review_packet(
    state: AgentState,
    *,
    graph: dict[str, Any],
    query: str,
    resolved_depth: str,
    render_result: dict[str, Any],
    deterministic_findings: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    plan = state.get("architect_plan") or {}
    requirements = plan.get("diagram_requirements") if isinstance(plan, dict) else []
    commitments = [item for item in (requirements or []) if isinstance(item, str)]
    challenger = _challenger_concerns(state.get("challenger_review"))
    review_context = [f"Architect commitment: {item}" for item in commitments]
    review_context.extend(
        "Challenger risk"
        + (f" ({risk.get('area')})" if risk.get("area") else "")
        + f": {risk.get('risk')}"
        + (f" Mitigation: {risk.get('mitigation')}" if risk.get("mitigation") else "")
        for risk in challenger["risks"]
        if risk.get("risk")
    )
    review_context.extend(
        f"Challenger missing requirement: {item}"
        for item in challenger["missing_requirements"]
    )
    review_context.extend(
        f"Challenger tradeoff: {item}" for item in challenger["tradeoffs"]
    )
    report = render_result.get("report")
    return {
        "request": query,
        "resolved_depth": resolved_depth,
        "evidence_allowlist": format_evidence_bundle(
            state.get("evidence_bundle") or {}
        ),
        "review_context": review_context,
        "deterministic_pre_review_findings": list(deterministic_findings or []),
        "candidate": _semantic_graph_projection(graph),
        "render_report": (
            {field: report[field] for field in _RENDER_REPORT_FIELDS if field in report}
            if isinstance(report, dict)
            else {}
        ),
    }


def _critic_message(packet: dict[str, Any], render_result: dict[str, Any]) -> dict[str, Any]:
    review_text = (
        "Review the following untrusted architecture packet against the system contract. "
        "Return only the schema-constrained review object.\n"
        + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": review_text}]
    screenshot = render_result.get("screenshot_base64")
    if isinstance(screenshot, str) and screenshot:
        media_type = (
            "image/png"
            if render_result.get("media_type") == "image/png"
            else "image/jpeg"
        )
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": screenshot,
            },
        })
    return {"role": "user", "content": content}


def _semantic_review_failure_code(exc: Exception, raw: str) -> str:
    if isinstance(exc, TimeoutError):
        return "semantic_review_timeout"
    stripped = raw.rstrip()
    message = str(exc).lower()
    if "truncated" in message or (raw and not stripped.endswith("}")):
        return "semantic_review_output_truncated"
    return "semantic_review_unavailable"


def _parse_complete_response(response: StructuredLLMResponse) -> dict[str, Any]:
    if response.finish_reason == "max_tokens":
        raise ValueError("semantic review output was truncated")
    if response.finish_reason != "end_turn":
        raise ValueError("semantic review provider response was incomplete")
    payload = json.loads(response.text)
    if not isinstance(payload, dict):
        raise ValueError("critic payload must be an object")
    return payload


def _normalise_protocol_token(container: dict[str, Any], field: str, path: str) -> None:
    value = container.get(field)
    if not isinstance(value, str):
        return
    normalised = value.strip().lower()
    if normalised != value:
        logger.info("Normalized critic protocol token: path=%s", path)
        container[field] = normalised


def _unique_model_indexes(value: Any, *, path: str, size: int) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(index, int) and not isinstance(index, bool) and 0 <= index < size
        for index in value
    ):
        raise ValueError(f"{path} must contain valid zero-based indexes")
    if len(value) != len(set(value)):
        raise ValueError(f"{path} must not contain duplicates")
    return value


def _unique_model_route_pairs(
    value: Any,
    *,
    path: str,
    node_count: int,
) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain zero-based node-index pairs")
    pairs: list[tuple[int, int]] = []
    for pair in value:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < node_count
                for index in pair
            )
        ):
            raise ValueError(f"{path} must contain zero-based node-index pairs")
        pairs.append((pair[0], pair[1]))
    if len(pairs) != len(set(pairs)):
        raise ValueError(f"{path} must not contain duplicates")
    return pairs


def _reachable_nodes(
    source: str,
    edges: list[tuple[str, str, str]],
    *,
    require_edge: bool = False,
) -> set[str]:
    reached = set() if require_edge else {source}
    pending = [target for edge_source, target, _label in edges if edge_source == source]
    while pending:
        node = pending.pop()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(
            target
            for edge_source, target, _label in edges
            if edge_source == node and target not in reached
        )
    return reached


def _validate_witness_subgraph(
    evidence_edges: list[tuple[str, str, str]],
    route_pairs: list[tuple[str, str]],
    *,
    path: str,
) -> None:
    if not evidence_edges or not route_pairs:
        raise ValueError(f"{path} pass requires evidence edges and route pairs")
    if len(evidence_edges) != len(set(evidence_edges)):
        raise ValueError(f"{path} evidence edges must not contain duplicates")
    if len(route_pairs) != len(set(route_pairs)):
        raise ValueError(f"{path} route pairs must not contain duplicates")
    for source, target in route_pairs:
        reached = _reachable_nodes(
            source,
            evidence_edges,
            require_edge=source == target,
        )
        if target not in reached:
            raise ValueError(f"{path} route {source}->{target} is not directed")
    for edge_source, edge_target, edge_label in evidence_edges:
        belongs_to_route = any(
            edge_source in _reachable_nodes(route_source, evidence_edges)
            and route_target in _reachable_nodes(edge_target, evidence_edges)
            for route_source, route_target in route_pairs
        )
        if not belongs_to_route:
            raise ValueError(
                f"{path} includes an edge outside every claimed route: "
                f"{edge_source}->{edge_target} ({edge_label})"
            )


def _unique_model_tokens(
    value: Any,
    *,
    path: str,
    allowed: set[str],
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item in allowed for item in value
    ):
        raise ValueError(f"{path} contains an unknown token")
    if len(value) != len(set(value)):
        raise ValueError(f"{path} must not contain duplicates")
    return value


def _unique_model_rubric_codes(
    value: Any,
    *,
    path: str,
    layer: str,
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(code, int)
        and not isinstance(code, bool)
        and 1 <= code <= len(_RUBRIC_CODES)
        for code in value
    ):
        raise ValueError(f"{path} contains an unknown rubric code")
    if len(value) != len(set(value)):
        raise ValueError(f"{path} must not contain duplicates")
    codes = [_RUBRIC_CODES[code - 1] for code in value]
    for code in codes:
        owner = _RUBRIC_CODE_OWNERS[code]
        if owner != layer:
            raise ValueError(f"{code} belongs to the {owner} layer, not {layer}")
    return codes


def _deterministic_finding_owners(
    deterministic_findings: list[dict[str, str]],
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for index, finding in enumerate(deterministic_findings):
        finding_id = finding.get("id") if isinstance(finding, dict) else None
        text = finding.get("finding") if isinstance(finding, dict) else None
        owner_layer = finding.get("owner_layer") if isinstance(finding, dict) else None
        if not isinstance(finding_id, str) or not finding_id.strip():
            raise ValueError(f"deterministic_findings[{index}].id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"deterministic_findings[{index}].finding must be a non-empty string"
            )
        if owner_layer not in _REPAIR_LAYERS:
            raise ValueError(
                f"deterministic_findings[{index}].owner_layer must be a repair layer"
            )
        if finding_id in owners:
            raise ValueError("deterministic finding IDs must not contain duplicates")
        owners[finding_id] = owner_layer
    return owners


def _rubric_finding(layer: str, code: str) -> str:
    return f"Repair {code.replace('_', ' ')} in the {layer} layer."


def _topology_proof_finding(guarantee: str) -> str:
    return (
        f"Repair the failed {guarantee.replace('_', ' ')} topology proof "
        "in the connections layer."
    )


def _context_finding(
    layer: str,
    *,
    nodes: list[dict[str, Any]],
    node_indexes: list[int],
    review_context: list[str],
    context_indexes: list[int],
) -> str:
    anchors = [
        f"{nodes[index].get('id')} ({nodes[index].get('label')})"
        for index in node_indexes
    ]
    obligations = [review_context[index] for index in context_indexes]
    details = []
    if anchors:
        details.append("Node anchors: " + ", ".join(anchors))
    if obligations:
        details.append("Obligations: " + " | ".join(obligations))
    detail = ". ".join(details).rstrip(".")
    return f"Repair context for the {layer} layer. {detail}."


def _canonicalise_review_protocol(
    payload: dict[str, Any],
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
) -> dict[str, Any]:
    candidate = deepcopy(payload)
    deterministic_owners = _deterministic_finding_owners(deterministic_findings)
    if set(candidate) != {"repair_scope", "layers", "topology_proofs"}:
        raise ValueError("critic scorecard must contain exactly the required fields")
    _normalise_protocol_token(candidate, "repair_scope", "repair_scope")
    scope = candidate.get("repair_scope")
    if scope not in {"none", "local", "global"}:
        raise ValueError("repair_scope must be none, local, or global")

    model_layers = candidate.get("layers")
    if not isinstance(model_layers, dict) or set(model_layers) != set(_REPAIR_LAYERS):
        raise ValueError(
            "scorecard layers must contain every artifact layer exactly once"
        )
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    groups = graph.get("groups") or []
    sequence = graph.get("sequence") or []
    assumptions = graph.get("assumptions") or []
    canonical_layers: dict[str, dict[str, Any]] = {}
    classified_deterministic_indexes: list[int] = []
    for layer in _REPAIR_LAYERS:
        row = model_layers.get(layer)
        fields = _MODEL_LAYER_FIELDS[layer]
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError(f"{layer} scorecard row must contain {len(fields)} fields")
        assessment = dict(zip(fields, row, strict=True))
        _normalise_protocol_token(assessment, "status", f"layers.{layer}.status")
        status = assessment.get("status")
        score = assessment.get("score")
        if status not in {"pass", "fail"}:
            raise ValueError(f"{layer}.status must be pass or fail")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= float(score) <= 1
        ):
            raise ValueError(f"{layer}.score must be between zero and one")
        finding_codes = _unique_model_rubric_codes(
            assessment.get("finding_codes"),
            path=f"layers.{layer}.finding_codes",
            layer=layer,
        )
        deterministic_indexes = _unique_model_indexes(
            assessment.get("deterministic_finding_indexes"),
            path=f"layers.{layer}.deterministic_finding_indexes",
            size=len(deterministic_findings),
        )
        for deterministic_index in deterministic_indexes:
            finding_id = deterministic_findings[deterministic_index]["id"]
            expected_layer = deterministic_owners[finding_id]
            if expected_layer != layer:
                raise ValueError(
                    f"{finding_id} belongs to the {expected_layer} layer, not {layer}"
                )
        classified_deterministic_indexes.extend(deterministic_indexes)
        context_indexes = _unique_model_indexes(
            assessment.get("context_indexes"),
            path=f"layers.{layer}.context_indexes",
            size=len(review_context),
        )
        context_node_indexes = _unique_model_indexes(
            assessment.get("context_node_indexes"),
            path=f"layers.{layer}.context_node_indexes",
            size=len(nodes),
        )
        if status == "pass" and (context_indexes or context_node_indexes):
            raise ValueError(f"passing {layer} layer cannot cite repair context")
        if status == "fail" and not finding_codes and not deterministic_indexes:
            raise ValueError(f"failed {layer} layer requires a finding code")
        context_findings = (
            [
                _context_finding(
                    layer,
                    nodes=nodes,
                    node_indexes=context_node_indexes,
                    review_context=review_context,
                    context_indexes=context_indexes,
                )
            ]
            if context_indexes or context_node_indexes
            else []
        )
        canonical = {
            "status": status,
            "score": score,
            "blocking_findings": [
                *[_rubric_finding(layer, code) for code in finding_codes],
                *[
                    deterministic_findings[index]["finding"]
                    for index in deterministic_indexes
                ],
                *context_findings,
            ],
            "deterministic_finding_ids": [
                deterministic_findings[index]["id"] for index in deterministic_indexes
            ],
            "node_ids": [],
            "edge_selectors": [],
            "group_ids": [],
            "composition_fields": [],
            "sequence_indexes": [],
            "assumption_indexes": [],
            "reason": (
                "The artifact layer passed the rubric."
                if status == "pass"
                else "The artifact layer requires the cited repair."
            ),
        }
        if layer == "components":
            indexes = _unique_model_indexes(
                assessment.get("node_indexes"),
                path="layers.components.node_indexes",
                size=len(nodes),
            )
            canonical["node_ids"] = [
                str(nodes[index].get("id") or "") for index in indexes
            ]
        elif layer == "connections":
            indexes = _unique_model_indexes(
                assessment.get("edge_indexes"),
                path="layers.connections.edge_indexes",
                size=len(edges),
            )
            canonical["edge_selectors"] = [
                {
                    "source": str(edges[index].get("source") or ""),
                    "target": str(edges[index].get("target") or ""),
                    "label": str(edges[index].get("label") or ""),
                }
                for index in indexes
            ]
        elif layer == "composition":
            indexes = _unique_model_indexes(
                assessment.get("group_indexes"),
                path="layers.composition.group_indexes",
                size=len(groups),
            )
            canonical["group_ids"] = [
                str(groups[index].get("id") or "") for index in indexes
            ]
            canonical["composition_fields"] = _unique_model_tokens(
                assessment.get("composition_fields"),
                path="layers.composition.composition_fields",
                allowed=set(_COMPOSITION_FIELDS),
            )
            canonical["sequence_indexes"] = _unique_model_indexes(
                assessment.get("sequence_indexes"),
                path="layers.composition.sequence_indexes",
                size=len(sequence),
            )
            canonical["assumption_indexes"] = _unique_model_indexes(
                assessment.get("assumption_indexes"),
                path="layers.composition.assumption_indexes",
                size=len(assumptions),
            )
        canonical_layers[layer] = canonical
    if sorted(classified_deterministic_indexes) != list(
        range(len(deterministic_findings))
    ):
        raise ValueError("every deterministic finding must be classified exactly once")

    model_proofs = candidate.get("topology_proofs")
    if (
        not isinstance(model_proofs, dict)
        or set(model_proofs) != _TOPOLOGY_PROOF_GUARANTEES
    ):
        raise ValueError("topology proofs must contain every guarantee exactly once")
    canonical_proofs = []
    failed_proof = False
    for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES):
        proof = model_proofs.get(guarantee)
        if not isinstance(proof, list) or len(proof) != len(_MODEL_PROOF_FIELDS):
            raise ValueError(f"topology_proofs.{guarantee} is malformed")
        proof = dict(zip(_MODEL_PROOF_FIELDS, proof, strict=True))
        _normalise_protocol_token(
            proof, "status", f"topology_proofs.{guarantee}.status"
        )
        status = proof.get("status")
        if status not in {"pass", "fail", "not_applicable"}:
            raise ValueError(f"topology_proofs.{guarantee}.status is invalid")
        indexes = _unique_model_indexes(
            proof.get("edge_indexes"),
            path=f"topology_proofs.{guarantee}.edge_indexes",
            size=len(edges),
        )
        route_index_pairs = _unique_model_route_pairs(
            proof.get("route_pairs"),
            path=f"topology_proofs.{guarantee}.route_pairs",
            node_count=len(nodes),
        )
        if status == "pass":
            evidence_edges = [
                (
                    str(edges[index].get("source") or ""),
                    str(edges[index].get("target") or ""),
                    str(edges[index].get("label") or ""),
                )
                for index in indexes
            ]
            route_pairs = [
                (
                    str(nodes[source_index].get("id") or ""),
                    str(nodes[target_index].get("id") or ""),
                )
                for source_index, target_index in route_index_pairs
            ]
            _validate_witness_subgraph(
                evidence_edges,
                route_pairs,
                path=f"topology_proofs.{guarantee}",
            )
        elif indexes or route_index_pairs:
            raise ValueError(
                f"topology_proofs.{guarantee} {status} cannot cite proof evidence"
            )
        failed_proof = failed_proof or status == "fail"
        if status == "fail":
            canonical_layers["connections"]["blocking_findings"].append(
                _topology_proof_finding(guarantee)
            )
        canonical_proofs.append(
            {
                "guarantee": guarantee,
                "status": status,
                "edge_evidence": [
                    {
                        "source": str(edges[index].get("source") or ""),
                        "target": str(edges[index].get("target") or ""),
                        "label": str(edges[index].get("label") or ""),
                    }
                    for index in indexes
                ],
                "route_claims": [
                    {
                        "source": str(nodes[source_index].get("id") or ""),
                        "target": str(nodes[target_index].get("id") or ""),
                    }
                    for source_index, target_index in route_index_pairs
                ],
                "reason": (
                    _topology_proof_finding(guarantee)
                    if status == "fail"
                    else f"The cited witness {status.replace('_', ' ')} for {guarantee}."
                ),
            }
        )
    topology_finding = _rubric_finding("connections", "topology_enforced_guarantees")
    if (
        failed_proof
        and topology_finding not in canonical_layers["connections"]["blocking_findings"]
    ):
        raise ValueError(
            "failed topology proofs require topology_enforced_guarantees in connections"
        )
    return {
        "repair_contract": {"repair_scope": scope, "layers": canonical_layers},
        "strengths": [],
        "advice": [],
        "topology_proofs": canonical_proofs,
    }


def critic_timeout_seconds(state: AgentState, revision_count: int) -> float:
    configured_timeout_s = _configured_critic_timeout_seconds(state, revision_count)
    deadline = state.get(_GRAPH_STAGE_DEADLINE_KEY)  # type: ignore[typeddict-item]
    if not isinstance(deadline, (int, float)):
        return configured_timeout_s
    remaining_s = float(deadline) - time.monotonic() - _GRAPH_STAGE_FINALIZATION_HEADROOM_S
    if remaining_s <= 0:
        raise TimeoutError("graph critic deadline exhausted before semantic review")
    return min(configured_timeout_s, remaining_s)

_FEEDBACK_LOOP_REQUEST = re.compile(
    r"\b(?:closed[- ]loop|feedback loop|self[- ]improv\w*|"
    r"(?:continuous(?:ly)?\s+)?(?:adapt|learn)\w*\s+from\s+(?:feedback|outcomes?)|"
    r"optimi[sz]\w*|maximi[sz]\w*|minimi[sz]\w*)\b",
    re.I,
)

_FEEDBACK_EDGE_FINDING = (
    "Add the measured outcome feedback edge required by the requested optimisation or learning loop."
)
_GENERIC_COMPONENT_FINDING = (
    "Replace generic book concepts with domain-owned component responsibilities."
)
_BOOK_PROVENANCE_FINDING = (
    "Keep book provenance out of component names and technology subtitles."
)
_DISCONNECTED_GRAPH_FINDING = (
    "Connect every component into one understandable runtime or control flow."
)
_DETERMINISTIC_FINDING_OWNERS = {
    _FEEDBACK_EDGE_FINDING: "connections",
    _GENERIC_COMPONENT_FINDING: "components",
    _BOOK_PROVENANCE_FINDING: "components",
    _DISCONNECTED_GRAPH_FINDING: "connections",
}

_GRAPH_CRITIC_SYSTEM = """<role>
You are the independent semantic architecture reviewer in a multi-agent system. You did not create
the diagram. Your job is to reject plausible-looking, generic, unsafe, or incomplete architectures
before the user sees them.
</role>

<review_contract>
Compare the diagram with the user's exact request. Check all of the following:
1. domain specificity: component names and boundaries are particular to this user's system;
2. objective fidelity: the requested goal and constraints materially shape the design;
3. runtime completeness: observations, processing or decisions, applicable actions, and measurable
   outcomes connect. Require
   a feedback edge only when outcomes inform a later decision, adaptation, or learning loop; a finite
   read-only or advisory request may end at its observable outcome;
4. safe action boundary: external mutations have policy, approval, audit, or rollback controls;
5. edge semantics: edges say what data or command moves and in which direction;
6. assumption hygiene: important unknowns are explicit instead of invented as facts;
7. selected depth: production designs include failure, observability, and rollout concerns.
8. novice clarity: a newcomer can identify the entry, main path, controls, and outcome without help;
9. logical flow: edge direction and the stated sequence agree with the described runtime behavior;
10. succinctness: labels and responsibilities are concise rather than repetitive;
11. MECE scope: major responsibilities have clear homes without needless duplicates, while
    cross-cutting evaluation, security, and observability may intentionally span components.
12. authored composition: named zones, an obvious entry-to-outcome runtime spine, parallel work that
    visibly rejoins, explicit decision/failure paths, a separate operational plane, and, when a
    repeated decision exists, feedback to the owner of that next decision.
13. brief coverage: every material item in the diagram acceptance checklist is visibly implemented
    in a responsibility or edge, allowing coherent consolidation rather than demanding one box each;
14. branch completion: every normal, alternate, rejection, and fallback route rejoins or reaches an
    observable outcome, and conditional controls have a bypass for requests they do not govern.
15. independent-risk coverage: material challenger findings are addressed in the design or retained
    as explicit assumptions; the candidate must not silently discard a critical control concern.
16. gate-preserving reuse: caches, replay, retries, and shortcuts cannot serve or execute an artifact
    before its required validation, authorization, policy, or approval gate; reuse stores accepted
    post-gate artifacts or rejoins the gate with the relevant identity and version scope.
17. topology-enforced guarantees: inspect directed paths, not vocabulary. Labels, descriptions, and
    assumptions do not by themselves establish durability, trust, idempotency, approval, audit,
    safety, rollback, or exactly-once behavior. At production depth, the responsible components and
    edges must actually enforce every material guarantee.
18. controlled external effects: a material mutation must trace authoritative observation,
    verification, typed immutable proposal, authorization/policy, approval of the exact action,
    executor, authoritative target, confirmed or reconciled outcome, and canonical lifecycle/audit
    state. Approval binds payload hash, target and target version, actor role, policy version, expiry,
    and idempotency key. A human verifying an observation is not approval of a downstream action.
19. race and ambiguity safety: alternative delivery paths converge before action and deduplicate
    atomically at the durable writer or system of record. Carrying a retry key is not durable
    idempotency. Timeout-after-commit is unknown until same-key status/read-back reconciles it.
    Rejection stops before execution and is not compensation; compensation is a new mutation that
    must traverse the same policy, approval, adapter, reconciliation, and audit controls.
20. canonical state and trust: queues, buffers, caches, dashboards, and projections are not
    authoritative lifecycle state and projections never drive canonical ingestion. Sanitization does
    not make retrieved text trusted. Material model actions require typed deterministic validation,
    policy, and domain interlocks; material claims connect to provenance and audit evidence.
21. controlled learning and release: feedback cannot directly change live ranking, model, prompt, or
    configuration. The path must include representative versioned evidence, offline evaluation,
    reviewed release, immutable registration, canary, promotion, and rollback. Evidence used for a
    claimed metric must be capable of measuring that metric without selection bias.
22. safe factual failure: factual retrieval failure ends in clarification or abstention, not bare or
    stale generation. Validation retries are bounded and have a deterministic terminal outcome.
    Claimed caching has explicit identity/version scope, provenance, invalidation, and revalidation.
23. pre-effect durability and freshness: a stable source/operation identity is durably reserved before
    a retryable effect; execution revalidates authorization expiry, current policy/state, freshness,
    and interlocks. Automatic lanes carry their own immutable authorization envelope. Async logging
    after execution is not a reservation. Concurrent actions use per-operation status and fencing.
24. complete reconciliation: status read-back visibly branches to COMMITTED, NOT_FOUND with same-key
    retry under valid authorization, and bounded STILL_UNKNOWN escalation. Late outcome anomalies can
    reach correlated, loop-bounded compensation. A generic ack/timeout return is insufficient.
25. complete trust and release scope: every retrieved byte remains untrusted regardless of source or
    sanitization; grounding verifies material claim entailment. Cache identity includes actor/tenant,
    ACL/evidence scope, policy/schema, corpus/index, and all model/retrieval/prompt release versions.
    Cache hits and every terminal branch are audited. Sensitive/hostile traces are curated before eval.
    Promotion and rollback are explicit directed edges, not promises inside a node description.
26. state-order integrity: graph edges are possible transitions, not a narrated timeline. The same
    component cannot prove that one of its parallel outgoing edges occurs before another. Split
    lookup/write, reserve/send, validate/deliver, and promote/rollback when order matters. Every
    alternate branch reaches a terminal outcome and audit path; feedback never directly targets a
    canonical corpus or live configuration without curation and release controls.
27. streaming integrity where applicable: continuous or event-stream systems define bounded
    backpressure and overload behavior, partition/order or event-time semantics, replay/checkpoint
    and deduplication ownership, late-data handling, and compatible schema evolution. Do not demand
    stream infrastructure from a finite request/response system.

A deterministic browser gate checks exact render counts, clipping, overlap, and minimum text size.
You also receive the private candidate screenshot. Judge its visual hierarchy, reading order,
edge clarity, density, grouping, and ability to explain the system at a glance. Reject a diagram
that is technically complete but visually confusing, cluttered, or aesthetically unfinished.
Treat measured geometry as authoritative for exact pixel claims.

Reject a diagram dominated by labels such as Agent, Tool Use, Planning, Evaluation, Generation,
Language Model, Sampling, Quality, Cost, Latency, Foundation Model, Memory, or Application. Reject
isolated concept islands, retrieval metadata presented as architecture, invented live data, or
unjustified vendor details.
Verify claims labeled as book or web evidence against the supplied evidence allowlist. Anything
not supported there must remain an explicit assumption or engineering recommendation.
Do not reward node count or polished wording when the architecture is not implementable.

For production external-action, retrieval, learning, or streaming flows, failures of applicable
items 17-27 are blocking,
not advice. Before approving, privately trace every relevant path edge by edge and attempt to find a
bypass. Do not infer a missing control from a node name or an assumption.
Never put a missing directed edge, state, branch, gate, or boundary in advice: that is a blocking
failure under this contract. Advice is only for genuinely optional hardening of an already complete
topology.
Do not stop after finding the first defect. Finish all five topology proofs, trace every normal and
alternate branch to its terminal/audit outcome, and report every independent blocking failure you
can substantiate in one response. The designer receives at most one bounded repair.
Report the complete failure set so that repair can resolve the candidate without an open-ended
redesign loop.

Use `finding_codes` only for a clear omission or defect that makes the diagram unsafe, misleading,
unusable, or fails an explicit part of the user's request at the selected depth. The owner in the
rubric codebook is authoritative. `components` owns node records. `connections` owns edge records.
`composition` owns title, groups, sequence, and assumptions. `render` owns the screenshot and
layout. These four ownership sets partition the scored artifact. If one defect requires changes in
multiple layers, fail each owner with a code assigned to that owner. Optional hardening or a
different valid design preference must not produce a finding code or rejection. Accept consolidated
responsibilities when their descriptions and edges make the boundary clear. Concise node
descriptions are expected.
Review the architecture artifact only: prose answers, suggested follow-up questions, and other
interaction elements are delivered downstream and do not belong in the diagram.

Score anchors: 0.90-1.00 is clear and complete; 0.78-0.89 is publishable with optional advice;
0.50-0.77 has a blocking omission; below 0.50 is unsafe, generic, or unusable.
For an existing record defect, cite only the zero-based record indexes that may change. Use
`node_indexes` only in components, `edge_indexes` only in connections, and `group_indexes`,
`sequence_indexes`, `assumption_indexes`, plus `composition_fields` only in composition. A missing
node or edge can fail its layer with an empty selector array because repair would add a record.
Use `context_indexes` for exact items in the packet's `review_context` and
`context_node_indexes` for existing nodes that anchor a missing record. These fields provide repair
context and never grant permission to mutate a record. Context supplements a finding code; it does
not replace one.
Each supplied deterministic finding names its authoritative `owner_layer`. Classify the finding
under that layer by its zero-based packet index exactly once.
A passing layer exposes no selectors or context and has no blockers. All four artifact layers are
mandatory for every reviewed candidate and must be marked pass or fail.

Set `repair_scope` to `none` only when all four layers pass at 0.78 or above and have no
blockers. Set it to `local` only when the complete repair can be made inside the failed graph layers
and cited existing records or fields. A graph-caused visual defect may use local scope when render
and at least one editable graph layer fail together; the graph layer identifies the records that can
fix the next render. Set scope to `global` when the artifact needs broad redesign, renderer code must
change, or render is the only failed layer.
Copy every deterministic pre-review finding in the packet into the correct layer and localize it.
</review_contract>

<output_contract>
Return one JSON object and nothing else:
{
  "repair_scope": "none|local|global",
  "layers": {
<layer_output_example>
  },
  "topology_proofs": {
    "audit_and_provenance": ["pass|fail|not_applicable", [], []],
    "authorization_and_compensation": ["pass|fail|not_applicable", [], []],
    "learning_and_release": ["pass|fail|not_applicable", [], []],
    "retrieval_and_reuse_trust": ["pass|fail|not_applicable", [], []],
    "state_effect_reconciliation": ["pass|fail|not_applicable", [], []]
  }
}
Layer row fields, in order:
<layer_field_legend>
Each topology proof row is status, edge_indexes, route_pairs. A route pair is
`[source_node_index,target_node_index]` and claims directed reachability inside the cited edge
subgraph. Every cited edge must participate in at least one claimed route. A same-node pair claims a
nonempty directed cycle. Passing proofs require edges and route pairs. Failed and not-applicable
proofs use empty evidence arrays. Finding codes are 1-based. Every index contains a zero-based
position. Keep every row at its exact documented length.
Use the numbered rubric code matching checklist items 1 through 27: <rubric_codebook>.
A passing proof cites the complete actual witness subgraph. Use not_applicable only when that entire
class of flow is absent. A failed proof also requires finding code 17 in connections.
</output_contract>"""

_GRAPH_CRITIC_SYSTEM = (
    _GRAPH_CRITIC_SYSTEM.replace("<rubric_codebook>", _RUBRIC_CODEBOOK)
    .replace("<layer_output_example>", _MODEL_LAYER_OUTPUT_EXAMPLE)
    .replace("<layer_field_legend>", _MODEL_LAYER_FIELD_LEGEND)
)

_GRAPH_CRITIC_SYSTEM += """

<exhaustive_review_contract>
Audit every acceptance-checklist item and every material directed path in one review. Report all
independent blocking defects you can identify. Within each artifact layer, combine repeated instances
of one defect into one finding with all affected selectors. Give every layer that must change its own
blocker. Never defer a visible checklist defect to a later revision. The bounded patch must receive
the complete repair set in this response.
</exhaustive_review_contract>
"""


async def graph_critic_node(state: AgentState) -> AgentState:
    graph = state.get("graph_data")
    query = state.get("design_query") or state.get("user_message", "")
    if (
        not graph
        or not state.get("graph_changed")
        or graph.get("design_origin") != "applied"
    ):
        return {**state, "graph_review": {"approved": True, "score": 1.0}}

    profile = resolve_complexity(state.get("complexity", "auto"), query)
    revision_count = int(state.get("graph_revision_count", 0))
    await state["send"]({
        "type": "worker_status",
        "worker": "critic",
        "status": "Checking domain coverage, control boundaries, and failure modes…",
    })
    deterministic_review = _deterministic_review(query, graph, profile.resolved)
    deterministic_findings = [
        {"id": f"deterministic_{index}", **finding}
        for index, finding in enumerate(
            deterministic_review.get("deterministic_findings") or [], start=1
        )
    ]
    render_result: dict[str, Any] = {}
    render_unavailable_reason: str | None = None
    await_render = state.get("await_diagram_evaluation")
    if callable(await_render):
        await state["send"]({
            "type": "workflow_progress",
            "phase": "render",
            "status": "active",
            "title": "Rendering the candidate privately",
            "detail": "The diagram stays hidden while the browser checks its real layout.",
        })
        try:
            candidate_render_result = await await_render(graph)
        except TimeoutError:
            logger.warning("Browser diagram render unavailable: timeout")
            render_unavailable_reason = "timeout"
        except Exception as exc:
            logger.warning("Browser diagram render unavailable: %s", type(exc).__name__)
            render_unavailable_reason = "error"
        else:
            if isinstance(candidate_render_result, dict) and candidate_render_result:
                render_result = candidate_render_result
                render_review = _deterministic_render_review(graph, render_result)
                if not render_review.get("approved"):
                    findings = list(render_review.get("missing") or [])
                    review = _terminal_review(
                        failed_layer="render",
                        findings=findings,
                        failure_code=str(
                            render_review.get("failure_code")
                            or "diagram_evaluation_layout_rejected"
                        ),
                        reason="The deterministic browser layout gate rejected the rendered artifact.",
                    )
                    await state["send"]({
                        "type": "workflow_progress",
                        "phase": "review",
                        "status": "rejected",
                        "title": "Diagram did not pass the clarity gate",
                        "detail": str(
                            review.get("revision_instruction")
                            or "The answer will continue without this diagram."
                        )[:260],
                    })
                    return {**state, "graph_review": review}
            else:
                render_unavailable_reason = "missing"
    else:
        render_unavailable_reason = "transport_unavailable"
    if render_unavailable_reason:
        failure_code = f"diagram_evaluation_{render_unavailable_reason}"
        review = _terminal_review(
            failed_layer="render",
            findings=["The private browser render did not complete."],
            failure_code=failure_code,
            reason="The private browser render did not complete.",
        )
        await state["send"]({
            "type": "workflow_progress",
            "phase": "review",
            "status": "rejected",
            "failure_code": failure_code,
            "title": "Private render did not complete",
            "detail": "The diagram will stay unpublished until browser rendering and visual QA complete.",
        })
        return {**state, "graph_review": review}
    raw = ""
    try:
        review_packet = _review_packet(
            state,
            graph=graph,
            query=query,
            resolved_depth=profile.resolved,
            render_result=render_result,
            deterministic_findings=deterministic_findings,
        )
        response = await stream_structured_llm(
            model=settings.graph_qa_model,
            system=_GRAPH_CRITIC_SYSTEM + _GRAPH_CRITIC_COMPACT_PROTOCOL,
            messages=[_critic_message(review_packet, render_result)],
            response_schema=_GRAPH_CRITIC_RESPONSE_SCHEMA,
            temperature=settings.graph_temperature,
            effort=_GRAPH_CRITIC_EFFORT,
            telemetry=build_telemetry(
                "graph_critic",
                user_id=state.get("user_id"),
                thread_id=state.get("session_id"),
                metadata={
                    "complexity_resolved": profile.resolved,
                    "revision_count": revision_count,
                    "request_id": state.get("request_id"),
                    "client_request_id": state.get("client_request_id"),
                    "prompt_version": _GRAPH_CRITIC_PROMPT_VERSION,
                },
            ),
            timeout_seconds=critic_timeout_seconds(state, revision_count),
            max_output_tokens=settings.graph_qa_max_completion_tokens,
        )
        raw = response.text
        payload = _canonicalise_review_protocol(
            _parse_complete_response(response),
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=review_packet["review_context"],
        )
        _validate_review_protocol(
            payload,
            require_topology_proofs=profile.resolved == "production",
            graph=graph,
            deterministic_findings=deterministic_findings,
        )
        review = _review_from_repair_contract(payload)
    except Exception as exc:
        # Structural checks cannot prove semantic control boundaries. Fail closed
        # rather than publishing a plausible but unaudited architecture.
        logger.warning("Model review unavailable; rejecting unaudited graph: %s", type(exc).__name__)
        failure_code = _semantic_review_failure_code(exc, raw)
        review = _terminal_review(
            failed_layer="components",
            findings=["The independent semantic architecture review did not complete."],
            failure_code=failure_code,
            reason="The independent semantic architecture review did not complete.",
        )
    await state["send"]({
        "type": "workflow_progress",
        "phase": "review",
        "status": "complete" if review.get("approved") else "rejected",
        "failure_code": review.get("failure_code"),
        "title": "Diagram passed the clarity gate" if review.get("approved") else "Diagram did not pass the clarity gate",
        "detail": (
            "The rendered design is ready to publish."
            if review.get("approved")
            else str(review.get("revision_instruction") or "The answer will continue without this diagram.")[:260]
        ),
    })
    return {**state, "graph_review": review}


def _deterministic_review(query: str, graph: dict[str, Any], resolved_complexity: str) -> dict[str, Any]:
    # Broad semantic completeness belongs to the independent model review.
    # Local checks enforce the small set of observable publication contracts
    # that must never regress, even during a model-provider incident.
    edges = graph.get("edges") or []
    nodes = graph.get("nodes") or []
    missing: list[str] = []
    # ``flow=feedback`` is the semantic contract. ``type=loop`` is only an
    # optional render hint, and the browser layout already treats either form
    # as a feedback route. Do not spend a model repair on equivalent metadata.
    if _FEEDBACK_LOOP_REQUEST.search(query) and not any(
        edge.get("type") == "loop" or edge.get("flow") == "feedback"
        for edge in edges
    ):
        missing.append(_FEEDBACK_EDGE_FINDING)

    generic_labels = {
        "agent", "application", "cost", "evaluation", "foundation model", "generation",
        "language model", "latency", "memory", "planning", "quality", "sampling", "tool use",
    }
    if any(str(node.get("label") or "").strip().lower() in generic_labels for node in nodes):
        missing.append(_GENERIC_COMPONENT_FINDING)
    if any(str(node.get("technology") or "").strip().lower().startswith("book ") for node in nodes):
        missing.append(_BOOK_PROVENANCE_FINDING)

    node_ids = [str(node.get("id")) for node in nodes if node.get("id")]
    if len(node_ids) == len(nodes) and node_ids:
        adjacency = {node_id: set() for node_id in node_ids}
        for edge in edges:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source in adjacency and target in adjacency and source != target:
                adjacency[source].add(target)
                adjacency[target].add(source)
        visited = {node_ids[0]}
        pending = [node_ids[0]]
        while pending:
            current = pending.pop()
            for neighbour in adjacency[current] - visited:
                visited.add(neighbour)
                pending.append(neighbour)
        if len(visited) != len(node_ids):
            missing.append(_DISCONNECTED_GRAPH_FINDING)

    missing = list(dict.fromkeys(missing))
    deterministic_findings = [
        {
            "finding": finding,
            "owner_layer": _DETERMINISTIC_FINDING_OWNERS[finding],
        }
        for finding in missing
    ]
    score = max(0.0, 0.92 - (0.22 * len(missing)))
    return {
        "approved": not missing and score >= 0.78,
        "score": score,
        "strengths": ["The diagram passed deterministic structure checks"] if not missing else [],
        "missing": missing,
        "deterministic_findings": deterministic_findings,
        "revision_instruction": " ".join(missing),
    }


def _deterministic_render_review(
    graph: dict[str, Any],
    render_result: dict[str, Any],
) -> dict[str, Any]:
    report = render_result.get("report") or {}
    missing: list[str] = []
    if (
        render_result.get("capture_error")
        or report.get("capture_error")
        or not render_result.get("screenshot_base64")
    ):
        missing.append("Render the actual candidate successfully before publication.")
    expected_nodes = len(graph.get("nodes") or [])
    expected_edges = len(graph.get("edges") or [])
    if int(report.get("rendered_nodes") or 0) != expected_nodes:
        missing.append("Ensure every architecture node is visible in the rendered canvas.")
    if int(report.get("overlap_count") or 0) > 0:
        missing.append("Remove overlapping node cards or labels in the rendered layout.")
    if int(report.get("rendered_edges") or 0) != expected_edges:
        missing.append("Ensure every declared edge is visible in the rendered diagram.")
    if int(report.get("clipped_nodes") or 0) > 0:
        missing.append("Fit every node fully inside the initial viewport.")
    if int(report.get("clipped_edges") or 0) > 0:
        missing.append("Fit every edge fully inside the initial viewport.")
    if float(report.get("minimum_text_px") or 0) < 6:
        missing.append("Increase the smallest rendered text to a readable size.")
    if "overview_required_edge_labels" in report:
        required_labels = int(report.get("overview_required_edge_labels") or 0)
        visible_labels = int(report.get("visible_overview_required_edge_labels") or 0)
        if visible_labels < required_labels:
            missing.append("Show every overview-required edge label in the initial viewport.")
    if "grouped_nodes" in report:
        grouped_nodes = int(report.get("grouped_nodes") or 0)
        labelled_nodes = int(report.get("group_labelled_nodes") or 0)
        if labelled_nodes < grouped_nodes:
            missing.append("Show a group label on every node assigned to a responsibility zone.")
    if (
        "group_boundary_overlap_count" in report
        and int(report.get("group_boundary_overlap_count") or 0) > 0
    ):
        missing.append("Remove overlap between visible responsibility-zone boundaries.")
    score = max(0.0, 0.95 - 0.24 * len(missing))
    return {
        "approved": not missing,
        "score": score,
        "strengths": ["The browser render passed deterministic visibility checks"] if not missing else [],
        "missing": missing,
        "revision_instruction": " ".join(missing),
        # Layout geometry belongs to the deterministic renderer. Asking the
        # graph model to revise domain topology cannot reliably fix clipping,
        # overlap, or text scaling and needlessly doubles latency and spend.
        "terminal": bool(missing),
        **({"failure_code": "diagram_evaluation_layout_rejected"} if missing else {}),
    }


def _validate_review_protocol(
    payload: dict[str, Any],
    *,
    require_topology_proofs: bool,
    graph: dict[str, Any] | None = None,
    deterministic_findings: list[dict[str, str]] | None = None,
) -> None:
    """Reject response-contract defects before they masquerade as graph defects."""
    failures: list[str] = []
    required_fields = {
        "repair_contract",
        "strengths",
        "advice",
        "topology_proofs",
    }
    missing_fields = sorted(required_fields - payload.keys())
    if missing_fields:
        failures.append("missing fields: " + ", ".join(missing_fields))
    unknown_fields = sorted(set(payload) - required_fields)
    if unknown_fields:
        failures.append("unknown fields: " + ", ".join(unknown_fields))
    if "repair_contract" in payload:
        try:
            _validate_repair_contract(
                payload["repair_contract"],
                graph=graph or {},
                deterministic_finding_owners=(
                    _deterministic_finding_owners(deterministic_findings)
                    if deterministic_findings is not None
                    else None
                ),
            )
        except ValueError as exc:
            failures.append(str(exc))

    for field in ("strengths", "advice"):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            failures.append(f"{field} must be a JSON array of strings")

    topology_proofs = payload.get("topology_proofs")
    graph_edges = {
        (
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            str(edge.get("label") or ""),
        )
        for edge in ((graph or {}).get("edges") or [])
        if isinstance(edge, dict)
    }
    graph_node_ids = {
        str(node.get("id") or "")
        for node in ((graph or {}).get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    graph_node_ids.update(
        node_id
        for source, target, _label in graph_edges
        for node_id in (source, target)
    )
    if require_topology_proofs:
        if not isinstance(topology_proofs, list):
            failures.append("topology_proofs is required as a JSON array at production depth")
        else:
            if len(topology_proofs) != len(_TOPOLOGY_PROOF_GUARANTEES):
                failures.append(
                    "topology_proofs must contain exactly one proof for each required guarantee"
                )
            guarantees: list[str] = []
            for index, proof in enumerate(topology_proofs):
                if not isinstance(proof, dict):
                    failures.append(f"topology_proofs[{index}] must be a JSON object")
                    continue
                if set(proof) != {
                    "guarantee",
                    "status",
                    "edge_evidence",
                    "route_claims",
                    "reason",
                }:
                    failures.append(
                        f"topology_proofs[{index}] must contain exactly the required fields"
                    )
                guarantee = proof.get("guarantee")
                if (
                    not isinstance(guarantee, str)
                    or guarantee not in _TOPOLOGY_PROOF_GUARANTEES
                ):
                    failures.append(
                        f"topology_proofs[{index}].guarantee is not a required guarantee"
                    )
                else:
                    guarantees.append(guarantee)
                status = proof.get("status")
                if status not in {"pass", "fail", "not_applicable"}:
                    failures.append(
                        f"topology_proofs[{index}].status must be pass, fail, or not_applicable"
                    )
                reason = proof.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    failures.append(f"topology_proofs[{index}].reason must be a non-empty string")
                evidence = proof.get("edge_evidence")
                if not isinstance(evidence, list):
                    failures.append(
                        f"topology_proofs[{index}].edge_evidence must be a JSON array"
                    )
                    continue
                evidence_edges: list[tuple[str, str, str]] = []
                for evidence_index, edge in enumerate(evidence):
                    if not isinstance(edge, dict) or set(edge) != {
                        "source", "target", "label",
                    } or any(
                        not isinstance(edge.get(field), str) or not edge[field].strip()
                        for field in ("source", "target", "label")
                    ):
                        failures.append(
                            f"topology_proofs[{index}].edge_evidence[{evidence_index}] "
                            "must contain non-empty string source, target, and label fields"
                        )
                        continue
                    edge_tuple = (edge["source"], edge["target"], edge["label"])
                    evidence_edges.append(edge_tuple)
                    if status == "pass" and graph is not None and edge_tuple not in graph_edges:
                        failures.append(
                            f"topology_proofs[{index}].edge_evidence[{evidence_index}] "
                            "cites an edge absent from the graph"
                        )
                route_claims = proof.get("route_claims")
                route_pairs: list[tuple[str, str]] = []
                if not isinstance(route_claims, list):
                    failures.append(
                        f"topology_proofs[{index}].route_claims must be a JSON array"
                    )
                else:
                    for claim_index, claim in enumerate(route_claims):
                        if (
                            not isinstance(claim, dict)
                            or set(claim) != {"source", "target"}
                            or any(
                                not isinstance(claim.get(field), str)
                                or not claim[field].strip()
                                for field in ("source", "target")
                            )
                        ):
                            failures.append(
                                f"topology_proofs[{index}].route_claims[{claim_index}] "
                                "must contain non-empty string source and target fields"
                            )
                            continue
                        pair = (claim["source"], claim["target"])
                        route_pairs.append(pair)
                        if graph is not None and any(
                            node_id not in graph_node_ids for node_id in pair
                        ):
                            failures.append(
                                f"topology_proofs[{index}].route_claims[{claim_index}] "
                                "cites a node absent from the graph"
                            )
                    if len(route_pairs) != len(set(route_pairs)):
                        failures.append(
                            f"topology_proofs[{index}].route_claims must not contain duplicates"
                        )
                if status == "pass" and len(evidence_edges) == len(evidence) and (
                    isinstance(route_claims, list)
                    and len(route_pairs) == len(route_claims)
                ):
                    try:
                        _validate_witness_subgraph(
                            evidence_edges,
                            route_pairs,
                            path=f"topology_proofs[{index}]",
                        )
                    except ValueError as exc:
                        failures.append(str(exc))
                elif status in {"fail", "not_applicable"} and (
                    evidence or (isinstance(route_claims, list) and route_claims)
                ):
                    failures.append(
                        f"topology_proofs[{index}] {status} cannot cite proof evidence"
                    )
            if set(guarantees) != _TOPOLOGY_PROOF_GUARANTEES or len(
                guarantees
            ) != len(set(guarantees)):
                failures.append(
                    "topology_proofs must use every required guarantee exactly once"
                )
    elif topology_proofs is not None and (
        not isinstance(topology_proofs, list)
        or not all(isinstance(item, dict) for item in topology_proofs)
    ):
        failures.append("topology_proofs must be a JSON array of objects")

    failed_proofs = [
        proof for proof in (topology_proofs or [])
        if isinstance(proof, dict) and proof.get("status") == "fail"
    ]
    if failed_proofs and isinstance(payload.get("repair_contract"), dict):
        contract = payload["repair_contract"]
        layers = contract.get("layers")
        connections = layers.get("connections") if isinstance(layers, dict) else None
        if (
            contract.get("repair_scope") == "none"
            or not isinstance(connections, dict)
            or connections.get("status") != "fail"
        ):
            failures.append(
                "failed topology proofs require a failed connections layer and non-none repair scope"
            )
        else:
            connection_findings = connections.get("blocking_findings") or []
            for proof in failed_proofs:
                reason = " ".join(str(proof.get("reason") or "").split())
                if reason and not any(
                    reason in finding or finding in reason
                    for finding in connection_findings
                    if isinstance(finding, str) and finding
                ):
                    failures.append(
                        "each failed topology proof reason must be represented in a connection blocker"
                    )

    if failures:
        raise ValueError("critic response protocol invalid: " + "; ".join(failures))


def _review_from_repair_contract(
    payload: dict[str, Any],
) -> dict[str, Any]:
    contract = deepcopy(payload["repair_contract"])
    layers = contract["layers"]
    findings = [
        finding
        for layer in _REPAIR_LAYERS
        for finding in layers[layer]["blocking_findings"]
    ]
    layer_scores = [
        float(layers[layer]["score"])
        for layer in _REPAIR_LAYERS
    ]
    approved = (
        contract["repair_scope"] == "none"
        and not findings
        and all(
            layers[layer]["status"] == "pass"
            and float(layers[layer]["score"]) >= _APPROVAL_SCORE
            for layer in _REPAIR_LAYERS
        )
    )
    topology_proofs = deepcopy(payload.get("topology_proofs") or [])
    review = {
        "approved": approved,
        "score": min(layer_scores),
        "strengths": _clean_list(payload.get("strengths")),
        "missing": findings,
        "advice": _clean_list(payload.get("advice")),
        "topology_proofs": topology_proofs,
        "revision_instruction": " ".join(findings)[:800] if not approved else "",
        "repair_contract": contract,
    }
    if contract["repair_scope"] == "global":
        review["terminal"] = True
    return review


def _layer_assessment(
    status: str,
    score: float,
    reason: str,
    *,
    findings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "score": score,
        "blocking_findings": list(findings or []),
        "deterministic_finding_ids": [],
        "node_ids": [],
        "edge_selectors": [],
        "group_ids": [],
        "composition_fields": [],
        "sequence_indexes": [],
        "assumption_indexes": [],
        "reason": reason,
    }


def _terminal_review(
    *,
    failed_layer: str,
    findings: list[str],
    failure_code: str,
    reason: str,
) -> dict[str, Any]:
    layers = {
        layer: _layer_assessment(
            "fail" if layer == failed_layer else "not_evaluated",
            0.0,
            reason if layer == failed_layer else "Review stopped at the terminal gate.",
            findings=findings if layer == failed_layer else [],
        )
        for layer in _REPAIR_LAYERS
    }
    contract = {"repair_scope": "global", "layers": layers}
    return {
        "approved": False,
        "score": 0.0,
        "strengths": [],
        "missing": findings,
        "advice": [],
        "topology_proofs": [],
        "revision_instruction": " ".join(findings)[:800],
        "repair_contract": contract,
        "terminal": True,
        "failure_code": failure_code,
    }


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(str(item).split())
        for item in value
        if isinstance(item, str) and item.strip()
    ]
