import hashlib
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
    LocalRepairAdmissionError,
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
_LOCAL_ADMISSION_RULES = {
    "insufficient_connection_additions",
    "missing_graph_anchor",
    "unbounded_collection",
    "invalid_local_admission",
}


class CriticProtocolError(ValueError):
    """Expose safe validation coordinates without logging model-owned values."""

    def __init__(self, message: str, *, path: str, rule: str) -> None:
        super().__init__(message)
        self.path = path if _SAFE_PROTOCOL_PATH.fullmatch(path) else None
        self.rule = rule if rule in _PROTOCOL_ERROR_RULES else None


_GRAPH_CRITIC_PROMPT_VERSION = "architecture_critic_v50"
# Sonnet 5 high effort can spend the full output allowance on adaptive thinking
# before emitting the required scorecard. Medium keeps the review inside one call.
_GRAPH_CRITIC_EFFORT = "medium"
_GRAPH_CRITIC_CORRECTION_EFFORT = "medium"
_GRAPH_CRITIC_CORRECTION_MAX_TOKENS = 8192
_MAX_GRAPH_CONTRACT_CORRECTIONS = 1
_MAX_GRAPH_CRITIC_PROVIDER_CALLS = 4
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
_PRODUCTION_ONLY_RUBRIC_CODES = frozenset(RUBRIC_CODES[16:])
_GRAPH_CRITIC_COMPACT_PROTOCOL = """

Response-size contract:
- Return only the fixed JSON scorecard; do not restate the request, graph, checklist, or reasoning.
- Use each rubric finding code at most once per layer. Select records by their zero-based positions
  in the candidate nodes, edges, groups, sequence, and assumptions arrays.
- If a repair changes several artifact types, fail each owning layer with its own finding code and
  indexes.
- Passing layers have empty finding and selector arrays. Preserve every required layer.
- Classify every server-supplied prior open obligation exactly once as resolved or still_fail.
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
        "addition_obligations",
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
_MODEL_PROOF_FIELDS = (
    "status",
    "edge_indexes",
    "route_pairs",
    "repair_obligation_indexes",
    "repair_edge_indexes",
)
_MODEL_LAYER_OUTPUT_EXAMPLE = ",\n".join(
    "    "
    + json.dumps(layer, ensure_ascii=False)
    + ": "
    + json.dumps(
        [0 if field.endswith("addition_count") else [] for field in fields],
        ensure_ascii=False,
    )
    for layer, fields in _MODEL_LAYER_FIELDS.items()
)
_MODEL_LAYER_FIELD_LEGEND = "\n".join(
    f"- {layer}: {', '.join(fields)}." for layer, fields in _MODEL_LAYER_FIELDS.items()
)


def _passing_model_layer_row(layer: str) -> list[Any]:
    return [
        0 if field.endswith("addition_count") else []
        for field in _MODEL_LAYER_FIELDS[layer]
    ]


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
                "items": {
                    "anyOf": [
                        {"type": "integer"},
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "integer"},
                                    {"type": "string"},
                                ]
                            },
                        },
                    ]
                },
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
                "prior_obligation_dispositions": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
        ),
        "$defs": definitions,
    }


_GRAPH_CRITIC_RESPONSE_SCHEMA = _critic_response_schema(require_topology_proofs=True)
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


def _content_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _owned_layer_fingerprints(graph: dict[str, Any]) -> dict[str, str]:
    nodes = _project_records(
        graph.get("nodes"),
        ("id", "label", "type", "technology", "description"),
    )
    edges = _project_records(
        graph.get("edges"),
        (
            "source",
            "target",
            "label",
            "technology",
            "sync",
            "flow",
            "description",
            "type",
        ),
    )
    composition = {
        "title": graph.get("title"),
        "groups": deepcopy(graph.get("groups") or []),
        "sequence": deepcopy(graph.get("sequence") or []),
        "assumptions": deepcopy(graph.get("assumptions") or []),
    }
    return {
        "components": _content_fingerprint(nodes),
        "connections": _content_fingerprint(edges),
        "composition": _content_fingerprint(composition),
    }


def _review_layer_fingerprints(graph: dict[str, Any]) -> dict[str, str]:
    owned = _owned_layer_fingerprints(graph)
    return {
        "components": owned["components"],
        "connections": _content_fingerprint(
            [owned["components"], owned["connections"]]
        ),
        "composition": _content_fingerprint(
            [
                owned["components"],
                owned["connections"],
                owned["composition"],
            ]
        ),
        "render": _content_fingerprint(
            {key: value for key, value in graph.items() if key != "version"}
        ),
    }


def _locked_review_layers(state: AgentState, graph: dict[str, Any]) -> set[str]:
    previous_graph = state.get("reviewed_graph_data")
    previous_review = state.get("graph_review") or {}
    previous_contract = previous_review.get("repair_contract")
    if not isinstance(previous_graph, dict) or not isinstance(previous_contract, dict):
        return set()
    previous_layers = previous_contract.get("layers")
    if not isinstance(previous_layers, dict):
        return set()

    before = _owned_layer_fingerprints(previous_graph)
    after = _owned_layer_fingerprints(graph)
    reopened: set[str] = {
        layer
        for layer in ("components", "connections", "composition")
        if isinstance(previous_layers.get(layer), dict)
        and previous_layers[layer].get("status") == "fail"
    }
    if before["components"] != after["components"]:
        reopened.update(("components", "connections", "composition"))
    if before["connections"] != after["connections"]:
        reopened.update(("connections", "composition"))
    if before["composition"] != after["composition"]:
        reopened.add("composition")
    return {
        layer
        for layer in ("components", "connections", "composition")
        if layer not in reopened
        and isinstance(previous_layers.get(layer), dict)
        and previous_layers[layer].get("status") == "pass"
    }


def _prior_open_obligations(
    state: AgentState,
    *,
    resolved_depth: str,
) -> list[dict[str, str]]:
    previous_review = state.get("graph_review") or {}
    previous_contract = previous_review.get("repair_contract")
    previous_layers = (
        previous_contract.get("layers") if isinstance(previous_contract, dict) else None
    )
    if not isinstance(previous_layers, dict):
        return []
    production_findings = {
        _rubric_finding(_RUBRIC_CODE_OWNERS[code], code)
        for code in _PRODUCTION_ONLY_RUBRIC_CODES
    }
    obligations: list[dict[str, str]] = []
    for layer in _REPAIR_LAYERS:
        assessment = previous_layers.get(layer)
        if not isinstance(assessment, dict) or assessment.get("status") != "fail":
            continue
        for finding in assessment.get("blocking_findings") or []:
            if not isinstance(finding, str) or not finding.strip():
                continue
            if resolved_depth != "production" and (
                finding in production_findings
                or finding.startswith("Repair the failed ")
            ):
                continue
            obligations.append(
                {
                    "id": _prior_obligation_id(layer=layer, finding=finding),
                    "layer": layer,
                    "finding": finding,
                }
            )
    return obligations


def _prior_obligation_id(*, layer: str, finding: str) -> str:
    """Return a stable opaque ID for one server-owned scorecard obligation."""
    digest = _content_fingerprint({"layer": layer, "finding": finding})
    return f"prior_{digest}"


def _review_packet(
    state: AgentState,
    *,
    graph: dict[str, Any],
    query: str,
    resolved_depth: str,
    render_result: dict[str, Any],
    deterministic_findings: list[dict[str, str]] | None = None,
    locked_layers: set[str] | None = None,
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
        "locked_pass_layers": sorted(locked_layers or set()),
        "prior_open_obligations": _prior_open_obligations(
            state,
            resolved_depth=resolved_depth,
        ),
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


def _model_connection_addition_obligations(
    value: Any,
    *,
    path: str,
    nodes: list[dict[str, Any]],
    component_addition_count: int,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array of exact connection obligations")
    obligations: list[dict[str, str]] = []

    def endpoint(reference: Any, *, endpoint_path: str) -> str:
        if isinstance(reference, int) and not isinstance(reference, bool):
            if 0 <= reference < len(nodes):
                node_id = str(nodes[reference].get("id") or "")
                if node_id:
                    return node_id
            raise ValueError(f"{endpoint_path} is not a valid node index")
        if isinstance(reference, str) and re.fullmatch(
            r"\$new_node_[1-9][0-9]*", reference
        ):
            position = int(reference.rsplit("_", 1)[1])
            if position <= component_addition_count:
                return reference
        raise ValueError(
            f"{endpoint_path} must identify an existing node or declared new-node slot"
        )

    for index, row in enumerate(value):
        obligation_path = f"{path}[{index}]"
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(
                f"{obligation_path} must be [source, target, required_contract]"
            )
        source = endpoint(row[0], endpoint_path=f"{obligation_path}.source")
        target = endpoint(row[1], endpoint_path=f"{obligation_path}.target")
        required_contract = row[2]
        if source == target:
            raise ValueError(f"{obligation_path} must use distinct endpoints")
        if not isinstance(required_contract, str) or not required_contract.strip():
            raise ValueError(
                f"{obligation_path}.required_contract must be a non-empty string"
            )
        obligations.append(
            {
                "source": source,
                "target": target,
                "required_contract": " ".join(required_contract.split()),
            }
        )
    keys = [
        (item["source"], item["target"], item["required_contract"])
        for item in obligations
    ]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{path} must not contain duplicates")
    return obligations


def _model_prior_obligation_dispositions(
    value: Any,
    *,
    prior_open_obligations: list[dict[str, str]],
    path: str = "prior_obligation_dispositions",
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    obligations_by_id = {
        obligation.get("id"): obligation
        for obligation in prior_open_obligations
        if isinstance(obligation.get("id"), str)
        and obligation["id"]
        == _prior_obligation_id(
            layer=obligation.get("layer", ""),
            finding=obligation.get("finding", ""),
        )
    }
    if len(obligations_by_id) != len(prior_open_obligations):
        raise ValueError("prior open obligations must have unique stable server IDs")
    dispositions: list[dict[str, Any]] = []
    for row_index, row in enumerate(value):
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or row[0] not in obligations_by_id
            or row[1] not in {"resolved", "still_fail"}
        ):
            raise ValueError(
                f"{path}[{row_index}] must be [prior_obligation_id, resolved|still_fail]"
            )
        dispositions.append({"prior_obligation_id": row[0], "status": row[1]})
    disposition_ids = [item["prior_obligation_id"] for item in dispositions]
    if len(disposition_ids) != len(set(disposition_ids)) or set(disposition_ids) != set(
        obligations_by_id
    ):
        raise ValueError(
            f"{path} must classify every prior open obligation exactly once"
        )
    return dispositions


def _preflight_review_protocol(
    payload: dict[str, Any],
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
    require_topology_proofs: bool = False,
    resolved_depth: str = "production",
    prior_open_obligations: list[dict[str, str]] | None = None,
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
    prior_open_obligations = prior_open_obligations or []
    component_addition_count = 0
    connection_addition_obligation_count = 0
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
            rubric_code = _RUBRIC_CODES[code - 1]
            if _RUBRIC_CODE_OWNERS[rubric_code] != layer:
                reject(f"{row_path}.finding_codes", "ownership_mismatch")
            if (
                resolved_depth != "production"
                and rubric_code in _PRODUCTION_ONLY_RUBRIC_CODES
            ):
                reject(f"{row_path}.finding_codes", "invalid_reference")

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

        deterministic_indexes = valid_indexes.get("deterministic_finding_indexes", [])
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
            elif layer == "components" and field == "addition_count":
                component_addition_count = value
        if "addition_obligations" in assessment:
            try:
                obligations = _model_connection_addition_obligations(
                    assessment["addition_obligations"],
                    path=f"{row_path}.addition_obligations",
                    nodes=graph.get("nodes") or [],
                    component_addition_count=component_addition_count,
                )
            except ValueError:
                reject(f"{row_path}.addition_obligations", "invalid_contract")
            else:
                connection_addition_obligation_count = len(obligations)
        if "composition_fields" in assessment:
            value = assessment["composition_fields"]
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item in _COMPOSITION_FIELDS for item in value
            ):
                reject(f"{row_path}.composition_fields", "invalid_reference")
            elif len(value) != len(set(value)):
                reject(f"{row_path}.composition_fields", "duplicate_reference")

        has_blocker = bool(finding_codes or deterministic_indexes)
        if not has_blocker:
            permission_fields = {
                "node_indexes",
                "edge_indexes",
                "group_indexes",
                "sequence_indexes",
                "assumption_indexes",
                "composition_fields",
                "addition_obligations",
            }
            has_permission = any(
                assessment.get(field)
                for field in permission_fields.intersection(assessment)
            ) or any(
                assessment.get(field)
                for field in fields
                if field.endswith("addition_count")
            )
            if (
                valid_indexes.get("context_indexes")
                or valid_indexes.get("context_node_indexes")
                or has_permission
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
            try:
                repair_obligation_indexes = _unique_model_indexes(
                    proof["repair_obligation_indexes"],
                    path=f"{path}.repair_obligation_indexes",
                    size=connection_addition_obligation_count,
                )
            except ValueError:
                reject(f"{path}.repair_obligation_indexes", "invalid_reference")
                repair_obligation_indexes = []
            try:
                repair_edge_indexes = _unique_model_indexes(
                    proof["repair_edge_indexes"],
                    path=f"{path}.repair_edge_indexes",
                    size=len(edges),
                )
            except ValueError:
                reject(f"{path}.repair_edge_indexes", "invalid_reference")
                repair_edge_indexes = []
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
                if repair_obligation_indexes or repair_edge_indexes:
                    reject(path, "unexpected_context")
            elif normalized_status == "fail":
                if edge_indexes or route_index_pairs:
                    reject(path, "unexpected_context")
                if not repair_obligation_indexes and not repair_edge_indexes:
                    reject(path, "missing_evidence")
            elif normalized_status == "not_applicable" and (
                edge_indexes
                or route_index_pairs
                or repair_obligation_indexes
                or repair_edge_indexes
            ):
                reject(path, "unexpected_context")

    try:
        _model_prior_obligation_dispositions(
            payload.get("prior_obligation_dispositions"),
            prior_open_obligations=prior_open_obligations,
        )
    except ValueError:
        reject("prior_obligation_dispositions", "incomplete_classification")

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
    resolved_depth: str = "production",
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
        if resolved_depth != "production" and code in _PRODUCTION_ONLY_RUBRIC_CODES:
            raise ValueError(f"{code} is not applicable at {resolved_depth} depth")
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


def _validate_prior_obligation_dispositions(
    dispositions: list[dict[str, Any]],
    *,
    prior_open_obligations: list[dict[str, str]],
    canonical_layers: dict[str, dict[str, Any]],
) -> None:
    obligations_by_id = {
        obligation["id"]: obligation for obligation in prior_open_obligations
    }
    for disposition in dispositions:
        prior = obligations_by_id[disposition["prior_obligation_id"]]
        current_layer = canonical_layers[prior["layer"]]
        current_findings = current_layer["blocking_findings"]
        finding_is_open = prior["finding"] in current_findings
        if disposition["status"] == "still_fail":
            if current_layer["status"] != "fail":
                raise ValueError(
                    "a still_fail prior obligation requires a current blocker in its owning layer"
                )
            if not finding_is_open:
                current_findings.append(prior["finding"])
        if disposition["status"] == "resolved" and finding_is_open:
            raise ValueError(
                "a resolved prior obligation cannot remain in its owning layer"
            )


def _canonicalise_review_protocol(
    payload: dict[str, Any],
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
    require_topology_proofs: bool = True,
    resolved_depth: str = "production",
    prior_open_obligations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    candidate = deepcopy(payload)
    prior_open_obligations = prior_open_obligations or []
    deterministic_owners = _deterministic_finding_owners(deterministic_findings)
    if set(candidate) != {
        "layers",
        "topology_proofs",
        "prior_obligation_dispositions",
    }:
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
    component_addition_count = 0
    connection_addition_obligations: list[dict[str, str]] = []
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
            resolved_depth=resolved_depth,
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
            "connection_addition_obligations": [],
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
            component_addition_count = canonical["addition_count"]
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
            connection_addition_obligations = _model_connection_addition_obligations(
                assessment.get("addition_obligations"),
                path="layers.connections.addition_obligations",
                nodes=nodes,
                component_addition_count=component_addition_count,
            )
            canonical["connection_addition_obligations"] = deepcopy(
                connection_addition_obligations
            )
            canonical["addition_count"] = len(connection_addition_obligations)
            canonical["context_node_ids"] = list(
                dict.fromkeys(
                    [
                        *canonical["context_node_ids"],
                        *[
                            endpoint
                            for obligation in connection_addition_obligations
                            for endpoint in (
                                obligation["source"],
                                obligation["target"],
                            )
                            if not endpoint.startswith("$new_node_")
                        ],
                    ]
                )
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

    dispositions = _model_prior_obligation_dispositions(
        candidate.get("prior_obligation_dispositions"),
        prior_open_obligations=prior_open_obligations,
    )

    if not require_topology_proofs:
        _validate_prior_obligation_dispositions(
            dispositions,
            prior_open_obligations=prior_open_obligations,
            canonical_layers=canonical_layers,
        )
        scope = _repair_scope_for_layers(canonical_layers)
        return {
            "repair_contract": {"repair_scope": scope, "layers": canonical_layers},
            "strengths": [],
            "advice": [],
            "topology_proofs": [],
            "prior_obligation_dispositions": dispositions,
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
        repair_obligation_indexes = _unique_model_indexes(
            proof.get("repair_obligation_indexes"),
            path=f"topology_proofs.{guarantee}.repair_obligation_indexes",
            size=len(connection_addition_obligations),
        )
        repair_edge_indexes = _unique_model_indexes(
            proof.get("repair_edge_indexes"),
            path=f"topology_proofs.{guarantee}.repair_edge_indexes",
            size=len(edges),
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
            if repair_obligation_indexes or repair_edge_indexes:
                raise ValueError(
                    f"topology_proofs.{guarantee} pass cannot cite repair references"
                )
        elif status == "fail":
            if indexes or route_index_pairs:
                raise ValueError(
                    f"topology_proofs.{guarantee} fail cannot cite proof evidence"
                )
            if not repair_obligation_indexes and not repair_edge_indexes:
                raise CriticProtocolError(
                    f"topology_proofs.{guarantee} fail requires an exact repair path",
                    path=f"topology_proofs.{guarantee}",
                    rule="missing_evidence",
                )
        elif (
            indexes
            or route_index_pairs
            or repair_obligation_indexes
            or repair_edge_indexes
        ):
            if repair_obligation_indexes or repair_edge_indexes:
                raise ValueError(
                    f"topology_proofs.{guarantee} {status} cannot cite repair references"
                )
            raise ValueError(
                f"topology_proofs.{guarantee} {status} cannot cite proof evidence"
            )
        failed_proof = failed_proof or status == "fail"
        if status == "fail":
            canonical_layers["connections"]["blocking_findings"].append(
                _topology_proof_finding(guarantee)
            )
            repair_edge_selectors = [
                {
                    "source": str(edges[index].get("source") or ""),
                    "target": str(edges[index].get("target") or ""),
                    "label": str(edges[index].get("label") or ""),
                }
                for index in repair_edge_indexes
            ]
            canonical_layers["connections"]["edge_selectors"] = list(
                {
                    (
                        selector["source"],
                        selector["target"],
                        selector["label"],
                    ): selector
                    for selector in [
                        *canonical_layers["connections"]["edge_selectors"],
                        *repair_edge_selectors,
                    ]
                }.values()
            )
        else:
            repair_edge_selectors = []
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
                "repair_obligations": [
                    deepcopy(connection_addition_obligations[index])
                    for index in repair_obligation_indexes
                ],
                "repair_edge_selectors": repair_edge_selectors,
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
    _validate_prior_obligation_dispositions(
        dispositions,
        prior_open_obligations=prior_open_obligations,
        canonical_layers=canonical_layers,
    )
    scope = _repair_scope_for_layers(canonical_layers)
    return {
        "repair_contract": {"repair_scope": scope, "layers": canonical_layers},
        "strengths": [],
        "advice": [],
        "topology_proofs": canonical_proofs,
        "prior_obligation_dispositions": dispositions,
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
    re.IGNORECASE,
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
5. edge semantics: every edge carries one distinct contract needed to follow behavior or prove a
   guarantee. Consolidate duplicate interactions. Parallel edges between one component pair must
   carry compatible distinct contracts, and reverse edges must name a response, acknowledgement,
   feedback, or control contract;
6. assumption hygiene: important unknowns are explicit instead of invented as facts;
7. selected depth: component responsibilities name the production owners for failure handling,
   observability, and rollout when those concerns apply.
8. novice clarity: authored groups and sequence make the entry, main path, controls, and outcome easy
   to locate in the screenshot. Classify unclear node text under components and unclear edge direction
   under connections. Exact screenshot geometry belongs to the deterministic render gate.
9. logical flow: the primary operational path starts at its real actor, event source, scheduled
   trigger, or first system receiver, then follows directed contracts to an observable outcome.
   Every branch rejoins that spine or ends at a named outcome. Sequence ordering belongs to authored
   composition and must be reviewed there.
10. succinctness: node labels and responsibilities are concise rather than repetitive;
11. MECE scope: a component earns a node when ownership, trust, authoritative state, a decision, an
    externally meaningful action, or an outcome changes. Fold other implementation detail into its
    owner and reject components whose only purpose is authoring, reviewing, explaining, laying out,
    or rendering this diagram. Cross-cutting evaluation, security, and observability may span
    components when they carry distinct operational responsibility.
12. authored composition: the title, named zones, assumptions, and one primary sequence expose the
    operational spine without contradicting graph records. Supporting, offline, control, and
    delivery paths remain subordinate to that sequence. Missing components, edges, or paths belong
    to their owning layers.
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
You also receive the private candidate screenshot. Use it to verify that the authored entry,
operational spine, controls, and outcome can be located. When the screenshot exposes confusing node
content, routes, density, grouping, or sequence, classify the defect under the authored field that
must change. Treat measured geometry as authoritative for exact pixel claims. A subjective visual
preference is advice, not a blocking finding.

The deterministic browser gate owns render geometry. Use the screenshot as evidence for authored
defects and assign each semantic defect to the graph field that must change. Use components for node
labels or responsibilities, connections for direction and edge semantics, and composition for title,
groups, sequence, or assumptions. A semantic clarity defect never belongs to render.

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
Review all blocking defects with full context and return every blocking defect in this scorecard.
The resulting repair contract is record-scoped and may authorize independent repairs at non-adjacent
records in the same connected candidate graph. This does not permit a disconnected candidate or
mutation of an uncited connecting record. Do not defer a known blocker to a later review.

Use `finding_codes` only for a clear omission or defect that makes the diagram unsafe, misleading,
unusable, or fails an explicit part of the user's request at the selected depth. The owner in the
rubric codebook is authoritative. `components` owns node records. `connections` owns edge records.
`composition` owns title, groups, sequence, and assumptions. These three sets partition the mutable
graph artifact. `render` records the deterministic browser assessment and exposes no model-editable
fields. Review each layer against the full graph context, then classify the defect by the fields that
must change. If one defect requires
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
Moving a node between groups changes two existing records. Cite both the source and destination
group indexes. A destination-only group selector is an invalid permission contract.
Use `context_indexes` for exact items in the packet's `review_context` and
`context_node_indexes` for existing nodes that anchor a missing record. These fields provide repair
context and never grant permission to mutate a record. Context supplements a finding code; it does
not replace one.
Each supplied deterministic finding names its authoritative `owner_layer`. Classify every supplied
finding exactly once under that owner layer.
A layer with no finding codes or deterministic finding indexes exposes no selectors or context.
All four artifact layers are mandatory for every reviewed candidate.
Set the component `addition_count` to the exact number of missing nodes required by the cited defect.
Existing-record defects and every passing layer use zero. Context node indexes are read-only anchors
for additions. In composition, use the three addition-count fields for the exact number of new
groups, sequence records, or assumptions; use zero for unchanged collections.
For connections, replace an aggregate addition count with `addition_obligations`. Each obligation is
`[source,target,required_contract]`. Existing endpoints are zero-based node indexes. A component
addition endpoint is `$new_node_N`, where N is its one-based addition slot. Use one obligation for
each required new edge. Source and target must differ. The server derives the connection addition
count from this list and grants only these directed endpoint pairs. `required_contract` states the
semantic meaning that the mandatory post-patch full-graph review must verify; it is not an exact edge
label and may be expressed by the patch through a concise label and description.
For a candidate with two existing nodes, `[0,1,"required behavior"]` adds an existing-to-existing
edge. `[0,"$new_node_1","required behavior"]` connects the first existing node to the first added
component. Integer `2` never represents a proposed node in that candidate. Every declared new-node
slot must appear in an obligation. At least one connection addition obligation for each newly added
connected region must use an existing candidate node as one endpoint. Context selectors explain the
repair but never attach a new region. Group moves use composition `group_indexes`, with both the
source and destination group indexes selected.
Component additions also require connection additions. When the candidate has groups, component
additions require a failed composition row with `groups` in `composition_fields` and either an
editable existing group or a declared group addition. Every composition addition count requires its
matching field in `composition_fields`. These are one repair plan across MECE owners, so fail every
owner whose records must change.

Copy every deterministic pre-review finding under its owning layer.
The packet may contain `prior_open_obligations`. Return one
`[prior_obligation_id,"resolved"|"still_fail"]` disposition for every item, copying its opaque
server ID exactly. A still-failing item requires a current blocker in its owning layer. The server
retains its original blocker text even when the current wording changes. A resolved item must be
absent from the current blockers. This classification is mandatory even when new defects are found.
</review_contract>

<output_contract>
Return one JSON object and nothing else:
{
  "layers": {
<layer_output_example>
  },
<topology_output_contract>
  ,"prior_obligation_dispositions": []
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
Report every blocking repair in one exhaustive scorecard. Exact record selectors remain the only
mutation authority and may span non-adjacent regions in one connected candidate. Uncited records
remain locked.
</repair_scope_contract>
"""


def _critic_system(
    *,
    require_topology_proofs: bool,
    resolved_depth: str = "production",
    locked_layers: set[str] | None = None,
) -> str:
    depth_contract = (
        f"\nThe selected UI depth is {resolved_depth} and is authoritative. At prototype depth, checklist items and "
        "finding codes 17 through 27 are out of scope, even when the request contains the word "
        "production. At production depth, all applicable criteria and topology proofs remain "
        "mandatory.\n"
    )
    locked_contract = ""
    if locked_layers:
        locked_contract = (
            "\nThe server has retained pass verdicts for these unchanged layers: "
            + ", ".join(sorted(locked_layers))
            + ". Return their passing empty rows. Do not invent findings or selectors for them.\n"
        )
    if not require_topology_proofs:
        topology_output = '  "topology_proofs": {}'
        topology_review = (
            "The unchanged connections layer retains its prior production topology proofs. Return "
            "the empty topology_proofs object required by this correction schema."
            if resolved_depth == "production"
            else "Prototype depth does not require formal topology proof rows. Return the empty "
            "topology_proofs object required by the schema."
        )
        return (
            _GRAPH_CRITIC_SYSTEM.replace(
                "<topology_output_contract>", topology_output
            ).replace("<topology_review_contract>", topology_review)
            + depth_contract
            + locked_contract
        )

    topology_output = """  "topology_proofs": {
  "audit_and_provenance": ["pass|fail|not_applicable", [], [], [], []],
  "authorization_and_compensation": ["pass|fail|not_applicable", [], [], [], []],
  "learning_and_release": ["pass|fail|not_applicable", [], [], [], []],
  "retrieval_and_reuse_trust": ["pass|fail|not_applicable", [], [], [], []],
  "state_effect_reconciliation": ["pass|fail|not_applicable", [], [], [], []]
  }"""
    topology_review = """Each topology proof row contains status, edge_indexes, route_pairs,
repair_obligation_indexes, and repair_edge_indexes. A route pair is
`[source_node_index,target_node_index]` and claims directed reachability inside the cited edge
subgraph. Every cited edge must participate in at least one claimed route. A same-node pair claims a
nonempty directed cycle. Passing proofs require edges and route pairs. Failed and not-applicable
proofs use empty evidence arrays. Passing and not-applicable proofs use no repair references. A
failed proof cites one or more exact repair paths using connection addition obligations or existing
edge indexes. Existing-edge repair indexes are projected into the connections repair selectors.
A passing proof cites the complete actual witness subgraph. Use
not_applicable only when that entire class of flow is absent. A failed proof also requires finding
code 17 in connections. Finish all five proofs and trace every normal and alternate branch to its
terminal and audit outcomes. Cite the smallest witness subgraph and directed endpoint claims for
each guarantee. Preserve every required proof."""
    return (
        _GRAPH_CRITIC_SYSTEM.replace(
            "<topology_output_contract>", topology_output
        ).replace("<topology_review_contract>", topology_review)
        + depth_contract
        + locked_contract
    )


async def _request_critic_scorecard(
    state: AgentState,
    *,
    review_packet: dict[str, Any],
    render_result: dict[str, Any],
    resolved_complexity: str,
    revision_count: int,
    correction: tuple[str, str] | None = None,
    contract_correction: dict[str, str] | None = None,
    locked_layers: set[str] | None = None,
    require_topology_proofs: bool | None = None,
) -> StructuredLLMResponse:
    message = _critic_message(review_packet, render_result)
    operation = "graph_critic"
    effort = _GRAPH_CRITIC_EFFORT
    max_output_tokens = settings.graph_qa_max_completion_tokens
    if require_topology_proofs is None:
        require_topology_proofs = resolved_complexity == "production"
    response_schema = (
        _GRAPH_CRITIC_RESPONSE_SCHEMA
        if require_topology_proofs
        else _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    )
    system = _critic_system(
        require_topology_proofs=require_topology_proofs,
        resolved_depth=resolved_complexity,
        locked_layers=locked_layers,
    )
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
                    "Your prior scorecard failed protocol validation. Correct it and return the "
                    "complete scorecard before the next repair. Preserve valid judgments, include "
                    "every blocking defect, and obey the exact "
                    f"{correction_contracts}.\n"
                    f"Validation error: {validation_error[:1000]}\n"
                    f"Prior scorecard: {invalid_response[:12000]}"
                ),
            }
        )
    if contract_correction is not None:
        operation = "graph_critic_contract_correction"
        prior_contract = (state.get("graph_review") or {}).get("repair_contract")
        message["content"].append(
            {
                "type": "text",
                "text": (
                    "The previous patch attempt was rejected at a server-owned validation "
                    "coordinate. Return a fresh exhaustive scorecard with permissions sufficient "
                    "for every current blocker before the patch model is called again. Preserve "
                    "valid judgments. Change selectors, addition obligations, append counts, and "
                    "group permissions only where required by the coordinate and the complete "
                    "candidate. For every existing-group move, authorize both source and "
                    "destination groups.\n"
                    f"Validation path: {contract_correction['path']}\n"
                    f"Validation rule: {contract_correction['rule']}\n"
                    "Prior repair contract: "
                    + json.dumps(
                        prior_contract, ensure_ascii=False, separators=(",", ":")
                    )[:12000]
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
            is_production=state.get("is_production"),
            metadata={
                "complexity_resolved": resolved_complexity,
                "revision_count": revision_count,
                "request_id": state.get("request_id"),
                "client_request_id": state.get("client_request_id"),
                "prompt_version": _GRAPH_CRITIC_PROMPT_VERSION,
                "protocol_correction": correction is not None,
                "contract_correction": contract_correction is not None,
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
        admission_error = (
            _local_admission_coordinate(exc.path, exc.rule)
            if isinstance(exc, LocalRepairAdmissionError)
            else _local_admission_coordinate(
                "repair_contract", "invalid_local_admission"
            )
        )
        logger.info(
            "Graph repair is outside the local patch lane: path=%s rule=%s",
            admission_error["path"],
            admission_error["rule"],
        )
        rejected = deepcopy(review)
        rejected.update(
            {
                "terminal": True,
                "failure_code": "graph_repair_nonlocal",
                "admission_error": admission_error,
                "revision_instruction": (
                    "The requested corrections exceed the bounded record-scoped patch contract. "
                    "The diagram was withheld without modifying the reviewed candidate."
                ),
            }
        )
        return rejected
    return review


def _local_admission_coordinate(path: str, rule: str) -> dict[str, str]:
    if not _SAFE_PROTOCOL_PATH.fullmatch(path) or rule not in _LOCAL_ADMISSION_RULES:
        return {"path": "repair_contract", "rule": "invalid_local_admission"}
    return {"path": path, "rule": rule}


def _review_admission_error(review: dict[str, Any]) -> dict[str, str] | None:
    admission_error = review.get("admission_error")
    if not isinstance(admission_error, dict):
        return None
    path = admission_error.get("path")
    rule = admission_error.get("rule")
    if (
        isinstance(path, str)
        and _SAFE_PROTOCOL_PATH.fullmatch(path)
        and isinstance(rule, str)
        and rule in _LOCAL_ADMISSION_RULES
    ):
        return {"path": path, "rule": rule}
    return None


def _completed_critic_review(
    response: StructuredLLMResponse,
    *,
    graph: dict[str, Any],
    deterministic_findings: list[dict[str, str]],
    review_context: list[str],
    require_topology_proofs: bool,
    resolved_depth: str = "production",
    locked_layers: set[str] | None = None,
    prior_open_obligations: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    try:
        raw_payload = _parse_complete_response(response)
        model_layers = raw_payload.get("layers")
        if isinstance(model_layers, dict):
            for layer in locked_layers or set():
                model_layers[layer] = _passing_model_layer_row(layer)
        _preflight_review_protocol(
            raw_payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=review_context,
            require_topology_proofs=require_topology_proofs,
            resolved_depth=resolved_depth,
            prior_open_obligations=prior_open_obligations,
        )
        payload = _canonicalise_review_protocol(
            raw_payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=review_context,
            require_topology_proofs=require_topology_proofs,
            resolved_depth=resolved_depth,
            prior_open_obligations=prior_open_obligations,
        )
        _validate_review_protocol(
            payload,
            require_topology_proofs=require_topology_proofs,
            graph=graph,
            deterministic_findings=deterministic_findings,
            prior_open_obligations=prior_open_obligations,
        )
    except CriticProtocolError:
        raise
    except ValueError as exc:
        raise _critic_protocol_error(exc) from exc
    review = _review_from_repair_contract(payload)
    return review


async def graph_critic_node(state: AgentState) -> AgentState:
    graph = state.get("graph_data")
    query = state.get("design_query") or state.get("user_message", "")
    if not graph or graph.get("design_origin") != "applied":
        return {**state, "graph_review": {"approved": True, "score": 1.0}}
    revision_count = int(state.get("graph_revision_count", 0))
    correction_pending = bool(state.get("graph_contract_correction_pending"))
    if (
        revision_count == 0
        and not state.get("graph_changed")
        and not correction_pending
    ):
        return {**state, "graph_review": {"approved": True, "score": 1.0}}

    profile = resolve_complexity(state.get("complexity", "auto"), query)
    revision_count = int(state.get("graph_revision_count", 0))
    contract_correction_count = int(state.get("graph_contract_correction_count", 0))
    critic_call_count = int(state.get("graph_critic_call_count", 0))

    async def request_scorecard(
        *, state_override: AgentState | None = None, **kwargs
    ) -> StructuredLLMResponse:
        nonlocal critic_call_count
        if critic_call_count >= _MAX_GRAPH_CRITIC_PROVIDER_CALLS:
            raise RuntimeError("graph critic provider-call ceiling reached")
        critic_call_count += 1
        return await _request_critic_scorecard(state_override or state, **kwargs)

    admission_correction_used = False
    locked_layers = _locked_review_layers(state, graph)
    require_topology_proofs = (
        profile.resolved == "production" and "connections" not in locked_layers
    )
    validation_error = state.get("graph_patch_validation_error")
    contract_correction = (
        validation_error
        if correction_pending
        and isinstance(validation_error, dict)
        and set(validation_error) == {"path", "rule"}
        and all(isinstance(value, str) for value in validation_error.values())
        else None
    )
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
                    return _reviewed_state(state, graph=graph, review=review)
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
        return _reviewed_state(state, graph=graph, review=review)
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
            locked_layers=locked_layers,
        )
        prior_open_obligations = review_packet["prior_open_obligations"]
        response = await request_scorecard(
            review_packet=review_packet,
            render_result=render_result,
            resolved_complexity=profile.resolved,
            revision_count=revision_count,
            contract_correction=contract_correction,
            locked_layers=locked_layers,
            require_topology_proofs=require_topology_proofs,
        )
        raw = response.text
        try:
            review = _completed_critic_review(
                response,
                graph=graph,
                deterministic_findings=deterministic_findings,
                review_context=review_packet["review_context"],
                require_topology_proofs=require_topology_proofs,
                resolved_depth=profile.resolved,
                locked_layers=locked_layers,
                prior_open_obligations=prior_open_obligations,
            )
        except (
            CriticProtocolError,
            ValueError,
            json.JSONDecodeError,
        ) as protocol_error:
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
            response = await request_scorecard(
                review_packet=review_packet,
                render_result=render_result,
                resolved_complexity=profile.resolved,
                revision_count=revision_count,
                correction=(raw, str(protocol_error)),
                contract_correction=contract_correction,
                locked_layers=locked_layers,
                require_topology_proofs=require_topology_proofs,
            )
            raw = response.text
            review = _completed_critic_review(
                response,
                graph=graph,
                deterministic_findings=deterministic_findings,
                review_context=review_packet["review_context"],
                require_topology_proofs=require_topology_proofs,
                resolved_depth=profile.resolved,
                locked_layers=locked_layers,
                prior_open_obligations=prior_open_obligations,
            )
            protocol_corrected = True
        review = _merge_locked_layer_verdicts(
            review,
            previous_review=state.get("graph_review") or {},
            locked_layers=locked_layers,
        )
        _validate_review_protocol(
            {
                "repair_contract": review["repair_contract"],
                "strengths": review.get("strengths") or [],
                "advice": review.get("advice") or [],
                "topology_proofs": review.get("topology_proofs") or [],
                "prior_obligation_dispositions": review.get(
                    "prior_obligation_dispositions"
                )
                or [],
            },
            require_topology_proofs=profile.resolved == "production",
            graph=graph,
            deterministic_findings=deterministic_findings,
            prior_open_obligations=prior_open_obligations,
        )
        if contract_correction is not None:
            review["contract_correction"] = deepcopy(contract_correction)
        review = _enforce_local_repair_admission(review, graph)
        admission_error = _review_admission_error(review)
        if (
            admission_error is not None
            and not protocol_corrected
            and contract_correction is None
            and contract_correction_count < _MAX_GRAPH_CONTRACT_CORRECTIONS
        ):
            validation_stage = "admission_correction"
            logger.warning(
                "Critic local admission rejected; requesting one contract correction: "
                "path=%s rule=%s",
                admission_error["path"],
                admission_error["rule"],
            )
            correction_state = {**state, "graph_review": review}
            admission_correction_used = True
            response = await request_scorecard(
                state_override=correction_state,
                review_packet=review_packet,
                render_result=render_result,
                resolved_complexity=profile.resolved,
                revision_count=revision_count,
                contract_correction=admission_error,
                locked_layers=locked_layers,
                require_topology_proofs=require_topology_proofs,
            )
            raw = response.text
            review = _completed_critic_review(
                response,
                graph=graph,
                deterministic_findings=deterministic_findings,
                review_context=review_packet["review_context"],
                require_topology_proofs=require_topology_proofs,
                resolved_depth=profile.resolved,
                locked_layers=locked_layers,
                prior_open_obligations=prior_open_obligations,
            )
            review = _merge_locked_layer_verdicts(
                review,
                previous_review=state.get("graph_review") or {},
                locked_layers=locked_layers,
            )
            _validate_review_protocol(
                {
                    "repair_contract": review["repair_contract"],
                    "strengths": review.get("strengths") or [],
                    "advice": review.get("advice") or [],
                    "topology_proofs": review.get("topology_proofs") or [],
                    "prior_obligation_dispositions": review.get(
                        "prior_obligation_dispositions"
                    )
                    or [],
                },
                require_topology_proofs=profile.resolved == "production",
                graph=graph,
                deterministic_findings=deterministic_findings,
                prior_open_obligations=prior_open_obligations,
            )
            review = _enforce_local_repair_admission(review, graph)
            review["admission_correction"] = deepcopy(admission_error)
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
    review["layer_fingerprints"] = _review_layer_fingerprints(graph)
    review_unavailable = review.get("review_status") == "unavailable"
    admission_error = _review_admission_error(review)
    if admission_error is not None:
        error_path = admission_error["path"]
        error_rule = admission_error["rule"]
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
    if (
        (review_unavailable or admission_error is not None)
        and error_path
        and error_rule
    ):
        progress_event.update(
            {
                "validation_stage": validation_stage,
                "validation_path": error_path,
                "validation_rule": error_rule,
            }
        )
    await state["send"](progress_event)
    reviewed_state = _reviewed_state(
        {**state, "graph_critic_call_count": critic_call_count},
        graph=graph,
        review=review,
    )
    if admission_correction_used:
        reviewed_state = {
            **reviewed_state,
            "graph_contract_correction_count": contract_correction_count + 1,
        }
    operation = reviewed_state.get("graph_operation")
    if (
        contract_correction is not None
        and review.get("review_status") == "completed"
        and isinstance(operation, dict)
    ):
        reviewed_state = {
            **reviewed_state,
            "graph_operation": {
                **operation,
                "status": "candidate",
                "failure_code": None,
            },
        }
    return reviewed_state


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
    prior_open_obligations: list[dict[str, str]] | None = None,
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
    unknown_fields = sorted(
        set(payload) - (required_fields | {"prior_obligation_dispositions"})
    )
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
    dispositions = payload.get("prior_obligation_dispositions")
    if dispositions is not None and (
        not isinstance(dispositions, list)
        or not all(
            isinstance(item, dict)
            and set(item) == {"prior_obligation_id", "status"}
            and isinstance(item.get("prior_obligation_id"), str)
            and bool(item.get("prior_obligation_id"))
            and item.get("status") in {"resolved", "still_fail"}
            for item in dispositions
        )
    ):
        failures.append(
            "prior_obligation_dispositions must be a JSON array of canonical dispositions"
        )
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
                required_proof_fields = {
                    "guarantee",
                    "status",
                    "edge_evidence",
                    "route_claims",
                    "reason",
                }
                optional_repair_fields = {
                    "repair_obligations",
                    "repair_edge_selectors",
                }
                if not required_proof_fields.issubset(proof) or (
                    set(proof) - required_proof_fields - optional_repair_fields
                ):
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
                repair_obligations = proof.get("repair_obligations", [])
                if not isinstance(repair_obligations, list) or not all(
                    isinstance(obligation, dict)
                    and set(obligation) == {"source", "target", "required_contract"}
                    and all(
                        isinstance(obligation.get(field), str)
                        and obligation[field].strip()
                        for field in ("source", "target", "required_contract")
                    )
                    for obligation in repair_obligations
                ):
                    failures.append(
                        f"topology_proofs[{index}].repair_obligations must contain exact repair paths"
                    )
                    repair_obligations = []
                connection_obligations = (
                    ((payload.get("repair_contract") or {}).get("layers") or {})
                    .get("connections", {})
                    .get("connection_addition_obligations", [])
                )
                if any(
                    obligation not in connection_obligations
                    for obligation in repair_obligations
                ):
                    failures.append(
                        f"topology_proofs[{index}].repair_obligations must reference declared connection additions"
                    )
                repair_edge_selectors = proof.get("repair_edge_selectors", [])
                if not isinstance(repair_edge_selectors, list) or not all(
                    isinstance(selector, dict)
                    and set(selector) == {"source", "target", "label"}
                    and all(
                        isinstance(selector.get(field), str) and selector[field].strip()
                        for field in ("source", "target", "label")
                    )
                    for selector in repair_edge_selectors
                ):
                    failures.append(
                        f"topology_proofs[{index}].repair_edge_selectors must contain exact existing edges"
                    )
                    repair_edge_selectors = []
                connection_edge_selectors = (
                    ((payload.get("repair_contract") or {}).get("layers") or {})
                    .get("connections", {})
                    .get("edge_selectors", [])
                )
                if any(
                    selector not in connection_edge_selectors
                    for selector in repair_edge_selectors
                ):
                    failures.append(
                        f"topology_proofs[{index}].repair_edge_selectors must reference declared connection edge repairs"
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
                if (
                    status == "fail"
                    and not repair_obligations
                    and not repair_edge_selectors
                ):
                    failures.append(
                        f"topology_proofs[{index}] fail requires an exact repair path"
                    )
                if status in {"pass", "not_applicable"} and (
                    repair_obligations or repair_edge_selectors
                ):
                    failures.append(
                        f"topology_proofs[{index}] {status} cannot cite repair references"
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

    if prior_open_obligations is not None and isinstance(dispositions, list):
        try:
            expected_ids = {item["id"] for item in prior_open_obligations}
            disposition_ids = [item["prior_obligation_id"] for item in dispositions]
            if (
                len(disposition_ids) != len(set(disposition_ids))
                or set(disposition_ids) != expected_ids
            ):
                raise ValueError(
                    "prior_obligation_dispositions must classify every server ID exactly once"
                )
            layers = (payload.get("repair_contract") or {}).get("layers") or {}
            _validate_prior_obligation_dispositions(
                dispositions,
                prior_open_obligations=prior_open_obligations,
                canonical_layers=layers,
            )
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(str(exc))

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
    prior_obligation_dispositions = deepcopy(
        payload.get("prior_obligation_dispositions") or []
    )
    review = {
        "approved": approved,
        "score": min(layer_scores),
        "review_status": "completed",
        "strengths": _clean_list(payload.get("strengths")),
        "missing": findings,
        "advice": _clean_list(payload.get("advice")),
        "topology_proofs": topology_proofs,
        "prior_obligation_dispositions": prior_obligation_dispositions,
        "revision_instruction": " ".join(findings)[:800] if not approved else "",
        "repair_contract": contract,
    }
    if contract["repair_scope"] == "global":
        review["terminal"] = True
    return review


def _merge_locked_layer_verdicts(
    review: dict[str, Any],
    *,
    previous_review: dict[str, Any],
    locked_layers: set[str],
) -> dict[str, Any]:
    if not locked_layers:
        return review
    contract = deepcopy(review["repair_contract"])
    previous_contract = previous_review.get("repair_contract")
    previous_layers = (
        previous_contract.get("layers") if isinstance(previous_contract, dict) else None
    )
    if not isinstance(previous_layers, dict):
        return review
    for layer in locked_layers:
        prior_layer = previous_layers.get(layer)
        if isinstance(prior_layer, dict) and prior_layer.get("status") == "pass":
            contract["layers"][layer] = deepcopy(prior_layer)
    contract["repair_scope"] = _repair_scope_for_layers(contract["layers"])
    topology_proofs = review.get("topology_proofs") or []
    if "connections" in locked_layers:
        topology_proofs = previous_review.get("topology_proofs") or topology_proofs
    merged = _review_from_repair_contract(
        {
            "repair_contract": contract,
            "strengths": review.get("strengths") or [],
            "advice": review.get("advice") or [],
            "topology_proofs": topology_proofs,
            "prior_obligation_dispositions": review.get("prior_obligation_dispositions")
            or [],
        }
    )
    merged["locked_layers"] = sorted(locked_layers)
    return merged


def _reviewed_state(
    state: AgentState,
    *,
    graph: dict[str, Any],
    review: dict[str, Any],
) -> AgentState:
    cleaned = dict(state)
    cleaned.pop("graph_patch_validation_error", None)
    return {
        **cleaned,
        "graph_review": review,
        "reviewed_graph_data": deepcopy(graph),
        "graph_contract_correction_pending": False,
    }  # type: ignore[return-value]


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
