import json
import logging
import re
import time
from copy import deepcopy
from typing import Any

from adapters.llm_adapter import build_telemetry
from agent.architecture_rubric import RUBRIC_CODES, RUBRIC_CODE_OWNERS
from agent.architecture_playbook import format_evidence_bundle
from agent.complexity import resolve_complexity
from agent.deadlines import critic_timeout_seconds as _configured_critic_timeout_seconds
from agent.graph_repair_contract import (
    APPROVAL_SCORE as _APPROVAL_SCORE,
    COMPOSITION_FIELDS as _COMPOSITION_FIELDS,
    REPAIR_LAYERS as _REPAIR_LAYERS,
    repair_scope_for_layers as _repair_scope_for_layers,
    validate_local_repair_admission as _validate_local_repair_admission,
    validate_repair_contract as _validate_repair_contract,
)
from agent.state import AgentState
from agent.stream_utils import StructuredLLMResponse, stream_structured_llm
from config import settings


logger = logging.getLogger(__name__)

_SAFE_PROTOCOL_PATH = re.compile(r"[A-Za-z0-9_$.\[\]]{1,96}")
_PROTOCOL_ERROR_RULES = {
    "duplicate_reference",
    "incomplete_classification",
    "invalid_contract",
    "invalid_enum",
    "invalid_range",
    "invalid_reference",
    "invalid_shape",
    "missing_finding",
    "missing_evidence",
    "ownership_mismatch",
    "unexpected_context",
}


class CriticProtocolError(ValueError):
    """Expose safe validation coordinates without logging model-owned values."""

    def __init__(self, message: str, *, path: str, rule: str) -> None:
        super().__init__(message)
        self.path = path if _SAFE_PROTOCOL_PATH.fullmatch(path) else None
        self.rule = rule if rule in _PROTOCOL_ERROR_RULES else None


_GRAPH_CRITIC_PROMPT_VERSION = "architecture_critic_v43"
# Sonnet 5 high effort can spend the full output allowance on adaptive thinking
# before emitting the required scorecard. Medium keeps the review inside one call.
_GRAPH_CRITIC_EFFORT = "medium"
_GRAPH_CRITIC_CORRECTION_EFFORT = "medium"
_GRAPH_CRITIC_CORRECTION_MAX_TOKENS = 8192
_GRAPH_STAGE_DEADLINE_KEY = "_graph_stage_deadline_s"
_GRAPH_STAGE_FINALIZATION_HEADROOM_S = 1.0
_MINIMUM_PUBLISHED_TEXT_PX = 11.0
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
  indexes.
- Passing layers have empty finding and selector arrays. Preserve every required layer.
"""


def _strict_object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


_RUBRIC_CODES = RUBRIC_CODES
_RUBRIC_CODE_OWNERS = RUBRIC_CODE_OWNERS
_RUBRIC_CODEBOOK = ", ".join(
    f"{index}={name}[{_RUBRIC_CODE_OWNERS[name]}]"
    for index, name in enumerate(_RUBRIC_CODES, start=1)
)

_MODEL_LAYER_FIELDS = {
    "components": (
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "node_indexes",
        "addition_count",
    ),
    "connections": (
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "edge_indexes",
        "addition_count",
    ),
    "composition": (
        "finding_codes",
        "deterministic_finding_indexes",
        "context_indexes",
        "context_node_indexes",
        "group_indexes",
        "composition_fields",
        "sequence_indexes",
        "assumption_indexes",
        "group_addition_count",
        "sequence_addition_count",
        "assumption_addition_count",
    ),
    "render": (
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
            0
            if field.endswith("addition_count")
            else []
            for field in fields
        ],
        ensure_ascii=False,
    )
    for layer, fields in _MODEL_LAYER_FIELDS.items()
)
_MODEL_LAYER_FIELD_LEGEND = "\n".join(
    f"- {layer}: {', '.join(fields)}." for layer, fields in _MODEL_LAYER_FIELDS.items()
)

# Anthropic compiles response schemas into a grammar. Repeating the full object schema for
# every named layer exceeds that compiler's size limit. The named MECE boundary stays explicit;
# shared tuple rows keep the provider grammar small. Python validates each field below.
_MODEL_LAYER_ROW_SCHEMA = {
    "type": "array",
    "items": {
        "anyOf": [
            {"type": "integer"},
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


def _critic_response_schema(*, require_topology_proofs: bool) -> dict[str, Any]:
    topology_proofs = (
        _strict_object_schema(
            {
                guarantee: {"$ref": "#/$defs/proof_row"}
                for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
            }
        )
        if require_topology_proofs
        else {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        }
    )
    definitions = {"layer_row": _MODEL_LAYER_ROW_SCHEMA}
    if require_topology_proofs:
        definitions["proof_row"] = _MODEL_PROOF_ROW_SCHEMA
    return {
        **_strict_object_schema(
            {
                "layers": _strict_object_schema(
                    {
                        layer: {"$ref": "#/$defs/layer_row"}
                        for layer in _MODEL_LAYER_FIELDS
                    }
                ),
                "topology_proofs": topology_proofs,
            }
        ),
        "$defs": definitions,
    }


_GRAPH_CRITIC_RESPONSE_SCHEMA = _critic_response_schema(
    require_topology_proofs=True
)
_GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA = _critic_response_schema(
    require_topology_proofs=False
)


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
            item for item in (graph.get("assumptions") or []) if isinstance(item, str)
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
    review_context = [f"Architect commitment: {item}" for item in commitments]
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


def _critic_message(
    packet: dict[str, Any], render_result: dict[str, Any]
) -> dict[str, Any]:
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
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": screenshot,
                },
            }
        )
    return {"role": "user", "content": content}


def _semantic_review_failure_code(exc: Exception, raw: str) -> str:
    if isinstance(exc, TimeoutError):
        return "semantic_review_timeout"
    stripped = raw.rstrip()
    message = str(exc).lower()
    if "truncated" in message or (raw and not stripped.endswith("}")):
        return "semantic_review_output_truncated"
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return "semantic_review_protocol_invalid"
    return "semantic_review_unavailable"


def _protocol_error_coordinates(exc: Exception) -> tuple[str | None, str | None]:
    if not isinstance(exc, CriticProtocolError):
        return None, None
    return exc.path, exc.rule


def _critic_protocol_error(exc: ValueError) -> CriticProtocolError:
    """Convert model-contract failures to safe coordinates at the critic boundary."""
    message = str(exc)
    path_match = re.search(
        r"(?:layers\.)?(components|connections|composition|render)"
        r"(?:\.([A-Za-z_]+))?",
        message,
    )
    path = "critic_scorecard"
    if path_match:
        path = f"layers.{path_match.group(1)}"
        if path_match.group(2):
            path += f".{path_match.group(2)}"
    elif "topology_proofs" in message or "topology proof" in message:
        path = "topology_proofs"
    elif "repair_scope" in message:
        path = "repair_scope"
    elif "deterministic finding" in message:
        path = "deterministic_findings"
    return CriticProtocolError(message, path=path, rule="invalid_contract")


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


def _model_addition_count(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def _preflight_review_protocol(
    payload: dict[str, Any],
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
    require_topology_proofs: bool = False,
) -> None:
    """Report independent compact-row defects in one bounded correction."""
    failures: list[tuple[str, str]] = []

    def reject(path: str, rule: str) -> None:
        coordinate = (path, rule)
        if coordinate not in failures and len(failures) < 16:
            failures.append(coordinate)

    layers = payload.get("layers")
    if not isinstance(layers, dict) or set(layers) != set(_MODEL_LAYER_FIELDS):
        reject("layers", "invalid_shape")
        layers = {}
    sizes = {
        "deterministic_finding_indexes": len(deterministic_findings),
        "context_indexes": len(review_context),
        "context_node_indexes": len(graph.get("nodes") or []),
        "node_indexes": len(graph.get("nodes") or []),
        "edge_indexes": len(graph.get("edges") or []),
        "group_indexes": len(graph.get("groups") or []),
        "sequence_indexes": len(graph.get("sequence") or []),
        "assumption_indexes": len(graph.get("assumptions") or []),
    }
    classified_deterministic_indexes: list[int] = []
    deterministic_owners = _deterministic_finding_owners(deterministic_findings)
    for layer, fields in _MODEL_LAYER_FIELDS.items():
        row = layers.get(layer)
        row_path = f"layers.{layer}"
        if not isinstance(row, list) or len(row) != len(fields):
            reject(row_path, "invalid_shape")
            continue
        assessment = dict(zip(fields, row, strict=True))
        finding_codes = assessment["finding_codes"]
        if not isinstance(finding_codes, list) or not all(
            isinstance(code, int)
            and not isinstance(code, bool)
            and 1 <= code <= len(_RUBRIC_CODES)
            for code in finding_codes
        ):
            reject(f"{row_path}.finding_codes", "invalid_reference")
            finding_codes = []
        elif len(finding_codes) != len(set(finding_codes)):
            reject(f"{row_path}.finding_codes", "duplicate_reference")
        for code in finding_codes:
            if _RUBRIC_CODE_OWNERS[_RUBRIC_CODES[code - 1]] != layer:
                reject(f"{row_path}.finding_codes", "ownership_mismatch")

        valid_indexes: dict[str, list[int]] = {}
        for field in fields:
            if field not in sizes:
                continue
            value = assessment[field]
            path = f"{row_path}.{field}"
            if not isinstance(value, list) or not all(
                isinstance(index, int)
                and not isinstance(index, bool)
                and 0 <= index < sizes[field]
                for index in value
            ):
                reject(path, "invalid_reference")
                valid_indexes[field] = []
            elif len(value) != len(set(value)):
                reject(path, "duplicate_reference")
                valid_indexes[field] = value
            else:
                valid_indexes[field] = value

        deterministic_indexes = valid_indexes.get(
            "deterministic_finding_indexes", []
        )
        classified_deterministic_indexes.extend(deterministic_indexes)
        for index in deterministic_indexes:
            finding_id = deterministic_findings[index]["id"]
            if deterministic_owners[finding_id] != layer:
                reject(
                    f"{row_path}.deterministic_finding_indexes",
                    "ownership_mismatch",
                )

        for field in fields:
            if not field.endswith("addition_count"):
                continue
            value = assessment[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reject(f"{row_path}.{field}", "invalid_range")
        if "composition_fields" in assessment:
            value = assessment["composition_fields"]
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item in _COMPOSITION_FIELDS
                for item in value
            ):
                reject(f"{row_path}.composition_fields", "invalid_reference")
            elif len(value) != len(set(value)):
                reject(f"{row_path}.composition_fields", "duplicate_reference")

        has_blocker = bool(finding_codes or deterministic_indexes)
        if not has_blocker and (
            valid_indexes.get("context_indexes")
            or valid_indexes.get("context_node_indexes")
        ):
            reject(row_path, "unexpected_context")

    if require_topology_proofs:
        proofs = payload.get("topology_proofs")
        if not isinstance(proofs, dict) or set(proofs) != _TOPOLOGY_PROOF_GUARANTEES:
            reject("topology_proofs", "invalid_shape")
            proofs = {}
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES):
            path = f"topology_proofs.{guarantee}"
            row = proofs.get(guarantee)
            if not isinstance(row, list) or len(row) != len(_MODEL_PROOF_FIELDS):
                reject(path, "invalid_shape")
                continue
            proof = dict(zip(_MODEL_PROOF_FIELDS, row, strict=True))
            status = proof["status"]
            normalized_status = (
                status.strip().lower() if isinstance(status, str) else None
            )
            if normalized_status not in {"pass", "fail", "not_applicable"}:
                reject(f"{path}.status", "invalid_enum")
            try:
                edge_indexes = _unique_model_indexes(
                    proof["edge_indexes"],
                    path=f"{path}.edge_indexes",
                    size=len(edges),
                )
            except ValueError:
                reject(f"{path}.edge_indexes", "invalid_reference")
                edge_indexes = []
            try:
                route_index_pairs = _unique_model_route_pairs(
                    proof["route_pairs"],
                    path=f"{path}.route_pairs",
                    node_count=len(nodes),
                )
            except ValueError:
                reject(f"{path}.route_pairs", "invalid_reference")
                route_index_pairs = []
            if normalized_status == "pass":
                evidence_edges = [
                    (
                        str(edges[index].get("source") or ""),
                        str(edges[index].get("target") or ""),
                        str(edges[index].get("label") or ""),
                    )
                    for index in edge_indexes
                ]
                route_pairs = [
                    (
                        str(nodes[source_index].get("id") or ""),
                        str(nodes[target_index].get("id") or ""),
                    )
                    for source_index, target_index in route_index_pairs
                ]
                try:
                    _validate_witness_subgraph(
                        evidence_edges,
                        route_pairs,
                        path=path,
                    )
                except CriticProtocolError as exc:
                    reject(path, exc.rule or "invalid_contract")
                except ValueError:
                    reject(path, "invalid_contract")
            elif normalized_status in {"fail", "not_applicable"} and (
                edge_indexes or route_index_pairs
            ):
                reject(path, "unexpected_context")

    if sorted(classified_deterministic_indexes) != list(
        range(len(deterministic_findings))
    ):
        reject("deterministic_findings", "incomplete_classification")
    if failures:
        summary = "; ".join(f"{path}:{rule}" for path, rule in failures)
        path, rule = failures[0]
        raise CriticProtocolError(
            "critic scorecard preflight invalid: " + summary,
            path=path,
            rule=rule,
        )


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
        raise CriticProtocolError(
            f"{path} pass requires evidence edges and route pairs",
            path=path,
            rule="missing_evidence",
        )
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
            raise ValueError(
                f"deterministic_findings[{index}].id must be a non-empty string"
            )
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
    require_topology_proofs: bool = True,
) -> dict[str, Any]:
    candidate = deepcopy(payload)
    deterministic_owners = _deterministic_finding_owners(deterministic_findings)
    if set(candidate) != {"layers", "topology_proofs"}:
        raise ValueError("critic scorecard must contain exactly the required fields")

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
        status = "fail" if finding_codes or deterministic_indexes else "pass"
        if status == "pass" and (context_indexes or context_node_indexes):
            raise ValueError(f"passing {layer} layer cannot cite repair context")
        score = 1.0 if status == "pass" else 0.0
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
            "context_node_ids": [
                str(nodes[index].get("id") or "") for index in context_node_indexes
            ],
            "addition_count": 0,
            "composition_append_counts": {},
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
            canonical["addition_count"] = _model_addition_count(
                assessment.get("addition_count"),
                path="layers.components.addition_count",
            )
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
            canonical["addition_count"] = _model_addition_count(
                assessment.get("addition_count"),
                path="layers.connections.addition_count",
            )
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
            canonical["composition_append_counts"] = {
                field: count
                for field, count in (
                    (
                        "groups",
                        _model_addition_count(
                            assessment.get("group_addition_count"),
                            path="layers.composition.group_addition_count",
                        ),
                    ),
                    (
                        "sequence",
                        _model_addition_count(
                            assessment.get("sequence_addition_count"),
                            path="layers.composition.sequence_addition_count",
                        ),
                    ),
                    (
                        "assumptions",
                        _model_addition_count(
                            assessment.get("assumption_addition_count"),
                            path="layers.composition.assumption_addition_count",
                        ),
                    ),
                )
                if count > 0
            }
        canonical_layers[layer] = canonical
    if sorted(classified_deterministic_indexes) != list(
        range(len(deterministic_findings))
    ):
        raise ValueError("every deterministic finding must be classified exactly once")

    scope = _repair_scope_for_layers(canonical_layers)

    if not require_topology_proofs:
        return {
            "repair_contract": {"repair_scope": scope, "layers": canonical_layers},
            "strengths": [],
            "advice": [],
            "topology_proofs": [],
        }

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
            raise CriticProtocolError(
                f"topology_proofs.{guarantee}.status is invalid",
                path=f"topology_proofs.{guarantee}.status",
                rule="invalid_enum",
            )
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


def critic_timeout_seconds(state: AgentState) -> float:
    configured_timeout_s = _configured_critic_timeout_seconds(state)
    deadline = state.get(_GRAPH_STAGE_DEADLINE_KEY)  # type: ignore[typeddict-item]
    if not isinstance(deadline, (int, float)):
        return configured_timeout_s
    remaining_s = (
        float(deadline) - time.monotonic() - _GRAPH_STAGE_FINALIZATION_HEADROOM_S
    )
    if remaining_s <= 0:
        raise TimeoutError("graph critic deadline exhausted before semantic review")
    return min(configured_timeout_s, remaining_s)


_FEEDBACK_LOOP_REQUEST = re.compile(
    r"\b(?:closed[- ]loop|feedback loop|self[- ]improv\w*|"
    r"(?:continuous(?:ly)?\s+)?(?:adapt|learn)\w*\s+from\s+(?:feedback|outcomes?)|"
    r"optimi[sz]\w*|maximi[sz]\w*|minimi[sz]\w*)\b",
    re.I,
)

_FEEDBACK_EDGE_FINDING = "Add the measured outcome feedback edge required by the requested optimisation or learning loop."
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
7. selected depth: component responsibilities name the production owners for failure handling,
   observability, and rollout when those concerns apply.
8. novice clarity: the screenshot makes the authored entry, main path, controls, and outcome easy to
   locate. Missing semantic records belong to their graph layer instead of render.
9. logical flow: directed edge paths agree with the runtime behavior. Sequence ordering belongs to
   authored composition and must be reviewed there.
10. succinctness: node labels and responsibilities are concise rather than repetitive;
11. MECE scope: major responsibilities have clear homes without needless duplicates, while
    cross-cutting evaluation, security, and observability may intentionally span components.
12. authored composition: the title, named zones, sequence, and assumptions organize the authored
    graph without contradicting its records. Missing components, edges, or paths belong to their
    owning layers.
13. brief coverage: every checklist item that requires a responsibility has a component owner.
    Missing transitions and path semantics belong to connections, and stated unknowns belong to
    composition;
14. branch completion: every normal, alternate, rejection, and fallback route rejoins or reaches an
    observable outcome, and conditional controls have a bypass for requests they do not govern.
15. independent-risk coverage: every material challenger risk that requires a responsibility has a
    named component owner. Required control paths belong to connections, and retained unknowns belong
    to composition.
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
Review all blocking defects with full context, then return the highest-priority local repair
region for this pass. The designer receives one bounded local repair contract.
Do not bundle unrelated regions into one repair request.

Use `finding_codes` only for a clear omission or defect that makes the diagram unsafe, misleading,
unusable, or fails an explicit part of the user's request at the selected depth. The owner in the
rubric codebook is authoritative. `components` owns node records. `connections` owns edge records.
`composition` owns title, groups, sequence, and assumptions. `render` owns the screenshot and
layout. These four ownership sets partition the mutable artifact. Review each layer against the full
graph context, then classify the defect by the fields that must change. If one defect requires
changes in multiple layers, fail each owner with a code assigned to that owner. Optional hardening or a
different valid design preference must not produce a finding code or rejection. Accept consolidated
responsibilities when their descriptions and edges make the boundary clear. Concise node
descriptions are expected.
Review the architecture artifact only: prose answers, suggested follow-up questions, and other
interaction elements are delivered downstream and do not belong in the diagram.

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
A layer with no finding codes or deterministic finding indexes exposes no selectors or context.
All four artifact layers are mandatory for every reviewed candidate.
Set each component or connection `addition_count` to the exact number of missing records required
by the cited defect. Existing-record defects and every passing layer use zero. Context node indexes
are read-only anchors for those additions. In composition, use the three addition-count fields for
the exact number of new groups, sequence records, or assumptions; use zero for unchanged collections.
Every connection addition must have at least two endpoint identities across declared component
additions and unique component or connection context nodes.
Component additions also require connection additions. When the candidate has groups, component
additions require a failed composition row with `groups` in `composition_fields` and either an
editable existing group or a declared group addition. Every composition addition count requires its
matching field in `composition_fields`. These are one repair plan across MECE owners, so fail every
owner whose records must change.

Copy deterministic pre-review findings that belong to the active local repair region.
</review_contract>

<output_contract>
Return one JSON object and nothing else:
{
  "layers": {
<layer_output_example>
  },
<topology_output_contract>
}
Layer row fields, in order:
<layer_field_legend>
Finding codes are 1-based. Every index contains a zero-based position. Keep every row at its exact
documented length.
Use the numbered rubric code matching checklist items 1 through 27: <rubric_codebook>.
<topology_review_contract>
</output_contract>"""

_GRAPH_CRITIC_SYSTEM = (
    _GRAPH_CRITIC_SYSTEM.replace("<rubric_codebook>", _RUBRIC_CODEBOOK)
    .replace("<layer_output_example>", _MODEL_LAYER_OUTPUT_EXAMPLE)
    .replace("<layer_field_legend>", _MODEL_LAYER_FIELD_LEGEND)
)

_GRAPH_CRITIC_SYSTEM += """

<repair_scope_contract>
Report the highest-priority local repair region per pass. Keep every other blocking defect for the next
pass. Use the same row schema and ownership rules, but only authorize mutation inside this single
repair region.
</repair_scope_contract>
"""

def _critic_system(*, require_topology_proofs: bool) -> str:
    if not require_topology_proofs:
        topology_output = '  "topology_proofs": {}'
        topology_review = (
            "Prototype depth does not require formal topology proof rows. Return the empty "
            "topology_proofs object required by the schema."
        )
        return (
            _GRAPH_CRITIC_SYSTEM.replace("<topology_output_contract>", topology_output)
            .replace("<topology_review_contract>", topology_review)
        )

    topology_output = """  "topology_proofs": {
  "audit_and_provenance": ["pass|fail|not_applicable", [], []],
  "authorization_and_compensation": ["pass|fail|not_applicable", [], []],
  "learning_and_release": ["pass|fail|not_applicable", [], []],
  "retrieval_and_reuse_trust": ["pass|fail|not_applicable", [], []],
  "state_effect_reconciliation": ["pass|fail|not_applicable", [], []]
  }"""
    topology_review = """Each topology proof row is status, edge_indexes, route_pairs. A route pair is
`[source_node_index,target_node_index]` and claims directed reachability inside the cited edge
subgraph. Every cited edge must participate in at least one claimed route. A same-node pair claims a
nonempty directed cycle. Passing proofs require edges and route pairs. Failed and not-applicable
proofs use empty evidence arrays. A passing proof cites the complete actual witness subgraph. Use
not_applicable only when that entire class of flow is absent. A failed proof also requires finding
code 17 in connections. Finish all five proofs and trace every normal and alternate branch to its
terminal and audit outcomes. Cite the smallest witness subgraph and directed endpoint claims for
each guarantee. Preserve every required proof."""
    return (
        _GRAPH_CRITIC_SYSTEM.replace("<topology_output_contract>", topology_output)
        .replace("<topology_review_contract>", topology_review)
    )


async def _request_critic_scorecard(
    state: AgentState,
    *,
    review_packet: dict[str, Any],
    render_result: dict[str, Any],
    resolved_complexity: str,
    revision_count: int,
    correction: tuple[str, str] | None = None,
) -> StructuredLLMResponse:
    message = _critic_message(review_packet, render_result)
    operation = "graph_critic"
    effort = _GRAPH_CRITIC_EFFORT
    max_output_tokens = settings.graph_qa_max_completion_tokens
    require_topology_proofs = resolved_complexity == "production"
    response_schema = (
        _GRAPH_CRITIC_RESPONSE_SCHEMA
        if require_topology_proofs
        else _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    )
    system = _critic_system(require_topology_proofs=require_topology_proofs)
    if correction is not None:
        operation = "graph_critic_protocol_correction"
        effort = _GRAPH_CRITIC_CORRECTION_EFFORT
        max_output_tokens = min(
            settings.graph_qa_max_completion_tokens,
            _GRAPH_CRITIC_CORRECTION_MAX_TOKENS,
        )
        invalid_response, validation_error = correction
        correction_contracts = "row ownership and selector contracts"
        if require_topology_proofs:
            correction_contracts = (
                "row ownership, selector, and topology-proof contracts"
            )
        message["content"].append(
            {
                "type": "text",
                "text": (
                    "Your prior scorecard failed protocol validation. Correct it and run the clean "
                    "focus pass before the next local repair. Keep every valid judgment "
                    "unchanged, add every blocking defect that was missed for the selected "
                    "repair region, and obey the exact "
                    f"{correction_contracts}.\n"
                    f"Validation error: {validation_error[:1000]}\n"
                    f"Prior scorecard: {invalid_response[:12000]}"
                ),
            }
        )
    return await stream_structured_llm(
        model=settings.graph_qa_model,
        system=system + _GRAPH_CRITIC_COMPACT_PROTOCOL,
        messages=[message],
        response_schema=response_schema,
        temperature=settings.graph_temperature,
        effort=effort,
        telemetry=build_telemetry(
            operation,
            user_id=state.get("user_id"),
            thread_id=state.get("session_id"),
            metadata={
                "complexity_resolved": resolved_complexity,
                "revision_count": revision_count,
                "request_id": state.get("request_id"),
                "client_request_id": state.get("client_request_id"),
                "prompt_version": _GRAPH_CRITIC_PROMPT_VERSION,
                "protocol_correction": correction is not None,
            },
        ),
        timeout_seconds=critic_timeout_seconds(state),
        max_output_tokens=max_output_tokens,
    )


def _enforce_local_repair_admission(
    review: dict[str, Any], graph: dict[str, Any]
) -> dict[str, Any]:
    contract = review.get("repair_contract")
    if not isinstance(contract, dict) or contract.get("repair_scope") != "local":
        return review
    try:
        _validate_local_repair_admission(contract, graph=graph)
    except ValueError as exc:
        logger.info("Graph repair is outside the local patch lane: %s", exc)
        rejected = deepcopy(review)
        rejected.update(
            {
                "terminal": True,
                "failure_code": "graph_repair_nonlocal",
                "revision_instruction": (
                    "The requested corrections exceed one bounded architecture region. "
                    "The diagram was withheld without modifying the reviewed candidate."
                ),
            }
        )
        return rejected
    return review


def _completed_critic_review(
    response: StructuredLLMResponse,
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
    require_topology_proofs: bool,
) -> dict[str, Any]:
    try:
        raw_payload = _parse_complete_response(response)
        _preflight_review_protocol(
            raw_payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=review_context,
            require_topology_proofs=require_topology_proofs,
        )
        payload = _canonicalise_review_protocol(
            raw_payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=review_context,
            require_topology_proofs=require_topology_proofs,
        )
        _validate_review_protocol(
            payload,
            require_topology_proofs=require_topology_proofs,
            graph=graph,
            deterministic_findings=deterministic_findings,
        )
    except CriticProtocolError:
        raise
    except ValueError as exc:
        raise _critic_protocol_error(exc) from exc
    return _review_from_repair_contract(payload)


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
    await state["send"](
        {
            "type": "worker_status",
            "worker": "critic",
            "status": "Checking domain coverage, control boundaries, and failure modes…",
        }
    )
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
        await state["send"](
            {
                "type": "workflow_progress",
                "phase": "render",
                "status": "active",
                "title": "Rendering the candidate privately",
                "detail": "The diagram stays hidden while the browser checks its real layout.",
            }
        )
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
                    await state["send"](
                        {
                            "type": "workflow_progress",
                            "phase": "review",
                            "status": "rejected",
                            "title": "Diagram did not pass the clarity gate",
                            "detail": str(
                                review.get("revision_instruction")
                                or "The answer will continue without this diagram."
                            )[:260],
                        }
                    )
                    return {**state, "graph_review": review}
            else:
                render_unavailable_reason = "missing"
    else:
        render_unavailable_reason = "transport_unavailable"
    if render_unavailable_reason:
        failure_code = f"diagram_evaluation_{render_unavailable_reason}"
        review = _reviewer_failure(
            failure_code=failure_code,
            reason="The private browser render did not complete.",
        )
        await state["send"](
            {
                "type": "workflow_progress",
                "phase": "review",
                "status": "rejected",
                "failure_code": failure_code,
                "title": "Private render did not complete",
                "detail": "The diagram will stay unpublished until browser rendering and visual QA complete.",
            }
        )
        return {**state, "graph_review": review}
    raw = ""
    validation_stage = "initial"
    protocol_corrected = False
    error_path: str | None = None
    error_rule: str | None = None
    try:
        review_packet = _review_packet(
            state,
            graph=graph,
            query=query,
            resolved_depth=profile.resolved,
            render_result=render_result,
            deterministic_findings=deterministic_findings,
        )
        response = await _request_critic_scorecard(
            state,
            review_packet=review_packet,
            render_result=render_result,
            resolved_complexity=profile.resolved,
            revision_count=revision_count,
        )
        raw = response.text
        try:
            review = _completed_critic_review(
                response,
                graph=graph,
                deterministic_findings=deterministic_findings,
                review_context=review_packet["review_context"],
                require_topology_proofs=profile.resolved == "production",
            )
        except (CriticProtocolError, ValueError, json.JSONDecodeError) as protocol_error:
            if (
                _semantic_review_failure_code(protocol_error, raw)
                == "semantic_review_output_truncated"
            ):
                raise
            if protocol_corrected:
                raise
            error_path, error_rule = _protocol_error_coordinates(protocol_error)
            logger.warning(
                "Critic protocol invalid; requesting one correction: "
                "type=%s stage=%s path=%s rule=%s",
                type(protocol_error).__name__,
                validation_stage,
                error_path,
                error_rule,
            )
            validation_stage = "correction"
            response = await _request_critic_scorecard(
                state,
                review_packet=review_packet,
                render_result=render_result,
                resolved_complexity=profile.resolved,
                revision_count=revision_count,
                correction=(raw, str(protocol_error)),
            )
            raw = response.text
            review = _completed_critic_review(
                response,
                graph=graph,
                deterministic_findings=deterministic_findings,
                review_context=review_packet["review_context"],
                require_topology_proofs=profile.resolved == "production",
            )
            protocol_corrected = True
        review = _enforce_local_repair_admission(review, graph)
    except Exception as exc:
        # Structural checks cannot prove semantic control boundaries. Fail closed
        # rather than publishing a plausible but unaudited architecture.
        failure_code = _semantic_review_failure_code(exc, raw)
        error_path, error_rule = _protocol_error_coordinates(exc)
        logger.warning(
            "Model review unavailable; rejecting unaudited graph: "
            "type=%s code=%s stage=%s path=%s rule=%s",
            type(exc).__name__,
            failure_code,
            validation_stage,
            error_path,
            error_rule,
        )
        review = _reviewer_failure(
            failure_code=failure_code,
            reason="The independent semantic architecture review did not complete.",
        )
    review_unavailable = review.get("review_status") == "unavailable"
    progress_event = {
        "type": "workflow_progress",
        "phase": "review",
        "status": "complete" if review.get("approved") else "rejected",
        "failure_code": review.get("failure_code"),
        "title": (
            "Diagram passed the clarity gate"
            if review.get("approved")
            else "Independent review did not complete"
            if review_unavailable
            else "Diagram did not pass the clarity gate"
        ),
        "detail": (
            "The rendered design is ready to publish."
            if review.get("approved")
            else str(
                review.get("revision_instruction")
                or "The answer will continue without this diagram."
            )[:260]
        ),
    }
    if review_unavailable and error_path and error_rule:
        progress_event.update(
            {
                "validation_stage": validation_stage,
                "validation_path": error_path,
                "validation_rule": error_rule,
            }
        )
    await state["send"](progress_event)
    return {**state, "graph_review": review}


def _deterministic_review(
    query: str, graph: dict[str, Any], resolved_complexity: str
) -> dict[str, Any]:
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
        edge.get("type") == "loop" or edge.get("flow") == "feedback" for edge in edges
    ):
        missing.append(_FEEDBACK_EDGE_FINDING)

    generic_labels = {
        "agent",
        "application",
        "cost",
        "evaluation",
        "foundation model",
        "generation",
        "language model",
        "latency",
        "memory",
        "planning",
        "quality",
        "sampling",
        "tool use",
    }
    if any(
        str(node.get("label") or "").strip().lower() in generic_labels for node in nodes
    ):
        missing.append(_GENERIC_COMPONENT_FINDING)
    if any(
        str(node.get("technology") or "").strip().lower().startswith("book ")
        for node in nodes
    ):
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
        "strengths": ["The diagram passed deterministic structure checks"]
        if not missing
        else [],
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
        missing.append(
            "Ensure every architecture node is visible in the rendered canvas."
        )
    if int(report.get("overlap_count") or 0) > 0:
        missing.append(
            "Remove overlapping node cards or labels in the rendered layout."
        )
    if int(report.get("rendered_edges") or 0) != expected_edges:
        missing.append("Ensure every declared edge is visible in the rendered diagram.")
    if int(report.get("clipped_nodes") or 0) > 0:
        missing.append("Fit every node fully inside the initial viewport.")
    if int(report.get("clipped_edges") or 0) > 0:
        missing.append("Fit every edge fully inside the initial viewport.")
    if float(report.get("minimum_text_px") or 0) < _MINIMUM_PUBLISHED_TEXT_PX:
        missing.append("Increase the smallest rendered text to a readable size.")
    if "overview_required_edge_labels" in report:
        required_labels = int(report.get("overview_required_edge_labels") or 0)
        visible_labels = int(report.get("visible_overview_required_edge_labels") or 0)
        if visible_labels < required_labels:
            missing.append(
                "Show every overview-required edge label in the initial viewport."
            )
    if "grouped_nodes" in report:
        grouped_nodes = int(report.get("grouped_nodes") or 0)
        labelled_nodes = int(report.get("group_labelled_nodes") or 0)
        if labelled_nodes < grouped_nodes:
            missing.append(
                "Show a group label on every node assigned to a responsibility zone."
            )
    if (
        "group_boundary_overlap_count" in report
        and int(report.get("group_boundary_overlap_count") or 0) > 0
    ):
        missing.append("Remove overlap between visible responsibility-zone boundaries.")
    score = max(0.0, 0.95 - 0.24 * len(missing))
    return {
        "approved": not missing,
        "score": score,
        "strengths": ["The browser render passed deterministic visibility checks"]
        if not missing
        else [],
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
            failures.append(
                "topology_proofs is required as a JSON array at production depth"
            )
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
                    failures.append(
                        f"topology_proofs[{index}].reason must be a non-empty string"
                    )
                evidence = proof.get("edge_evidence")
                if not isinstance(evidence, list):
                    failures.append(
                        f"topology_proofs[{index}].edge_evidence must be a JSON array"
                    )
                    continue
                evidence_edges: list[tuple[str, str, str]] = []
                for evidence_index, edge in enumerate(evidence):
                    if (
                        not isinstance(edge, dict)
                        or set(edge)
                        != {
                            "source",
                            "target",
                            "label",
                        }
                        or any(
                            not isinstance(edge.get(field), str)
                            or not edge[field].strip()
                            for field in ("source", "target", "label")
                        )
                    ):
                        failures.append(
                            f"topology_proofs[{index}].edge_evidence[{evidence_index}] "
                            "must contain non-empty string source, target, and label fields"
                        )
                        continue
                    edge_tuple = (edge["source"], edge["target"], edge["label"])
                    evidence_edges.append(edge_tuple)
                    if (
                        status == "pass"
                        and graph is not None
                        and edge_tuple not in graph_edges
                    ):
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
                if (
                    status == "pass"
                    and len(evidence_edges) == len(evidence)
                    and (
                        isinstance(route_claims, list)
                        and len(route_pairs) == len(route_claims)
                    )
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
            if set(guarantees) != _TOPOLOGY_PROOF_GUARANTEES or len(guarantees) != len(
                set(guarantees)
            ):
                failures.append(
                    "topology_proofs must use every required guarantee exactly once"
                )
    elif topology_proofs is not None and (
        not isinstance(topology_proofs, list)
        or not all(isinstance(item, dict) for item in topology_proofs)
    ):
        failures.append("topology_proofs must be a JSON array of objects")

    failed_proofs = (
        [
            proof
            for proof in (topology_proofs or [])
            if isinstance(proof, dict) and proof.get("status") == "fail"
        ]
        if require_topology_proofs
        else []
    )
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
    layer_scores = [float(layers[layer]["score"]) for layer in _REPAIR_LAYERS]
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
        "review_status": "completed",
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


def _terminal_review(
    *,
    failed_layer: str,
    findings: list[str],
    failure_code: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "approved": False,
        "review_status": "completed",
        "strengths": [],
        "missing": findings,
        "advice": [],
        "topology_proofs": [],
        "revision_instruction": reason + " " + " ".join(findings)[:800],
        "failed_layer": failed_layer,
        "terminal": True,
        "failure_code": failure_code,
    }


def _reviewer_failure(*, failure_code: str, reason: str) -> dict[str, Any]:
    """Represent reviewer availability outside the four artifact layers."""
    return {
        "approved": False,
        "strengths": [],
        "advice": [],
        "topology_proofs": [],
        "revision_instruction": reason,
        "terminal": True,
        "review_status": "unavailable",
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
