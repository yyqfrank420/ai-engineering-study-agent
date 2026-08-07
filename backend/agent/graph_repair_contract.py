from __future__ import annotations

import math
from typing import Any


REPAIR_LAYERS = ("components", "connections", "composition", "render")
COMPOSITION_FIELDS = ("title", "groups", "sequence", "assumptions")
REPAIR_LAYER_PATCH_FIELDS = {
    "components": frozenset({"add_nodes", "update_nodes", "remove_nodes"}),
    "connections": frozenset({"add_edges", "update_edges", "remove_edges"}),
    "composition": frozenset(COMPOSITION_FIELDS),
    "render": frozenset(),
}
APPROVAL_SCORE = 0.78

_ASSESSMENT_FIELDS = {
    "status",
    "score",
    "blocking_findings",
    "deterministic_finding_ids",
    "node_ids",
    "edge_selectors",
    "group_ids",
    "composition_fields",
    "sequence_indexes",
    "assumption_indexes",
    "reason",
}


def _unique_strings(value: Any, field: str, failures: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        failures.append(f"{field} must be an array of non-empty strings")
        return []
    if len(value) != len(set(value)):
        failures.append(f"{field} must not contain duplicates")
    return value


def _unique_indexes(value: Any, field: str, failures: list[str]) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0
        for item in value
    ):
        failures.append(f"{field} must be an array of non-negative integers")
        return []
    if len(value) != len(set(value)):
        failures.append(f"{field} must not contain duplicates")
    return value


def validate_repair_contract(
    contract: Any,
    *,
    graph: dict[str, Any],
    deterministic_finding_owners: dict[str, str] | None = None,
) -> None:
    """Validate critic ownership and exact mutation selectors against one graph."""
    failures: list[str] = []
    if not isinstance(contract, dict) or set(contract) != {"repair_scope", "layers"}:
        raise ValueError("repair_contract must contain exactly repair_scope and layers")
    scope = contract.get("repair_scope")
    if scope not in {"none", "local", "global"}:
        failures.append("repair_scope must be none, local, or global")
    layers = contract.get("layers")
    if not isinstance(layers, dict) or set(layers) != set(REPAIR_LAYERS):
        failures.append(
            "layers must contain exactly components, connections, composition, and render"
        )
        layers = {}

    node_ids = {
        str(node.get("id"))
        for node in (graph.get("nodes") or [])
        if isinstance(node, dict) and node.get("id")
    }
    edge_selectors = {
        (
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            str(edge.get("label") or ""),
        )
        for edge in (graph.get("edges") or [])
        if isinstance(edge, dict)
    }
    group_ids = {
        str(group.get("id"))
        for group in (graph.get("groups") or [])
        if isinstance(group, dict) and group.get("id")
    }
    failed_layers: set[str] = set()
    all_findings: list[str] = []
    classified_deterministic_ids: list[str] = []
    for layer in REPAIR_LAYERS:
        assessment = layers.get(layer)
        if not isinstance(assessment, dict) or set(assessment) != _ASSESSMENT_FIELDS:
            failures.append(f"{layer} assessment must contain exactly the required fields")
            continue
        status = assessment.get("status")
        if status not in {"pass", "fail"}:
            failures.append(f"{layer}.status must be pass or fail")
        score = assessment.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0.0 <= float(score) <= 1.0
        ):
            failures.append(f"{layer}.score must be a finite number between 0 and 1")
        findings = _unique_strings(
            assessment.get("blocking_findings"),
            f"{layer}.blocking_findings",
            failures,
        )
        layer_deterministic_ids = _unique_strings(
            assessment.get("deterministic_finding_ids"),
            f"{layer}.deterministic_finding_ids",
            failures,
        )
        if deterministic_finding_owners is not None:
            for finding_id in layer_deterministic_ids:
                expected_layer = deterministic_finding_owners.get(finding_id)
                if expected_layer is not None and expected_layer != layer:
                    failures.append(
                        f"{finding_id} belongs to the {expected_layer} layer, not {layer}"
                    )
        selected_node_ids = _unique_strings(
            assessment.get("node_ids"), f"{layer}.node_ids", failures
        )
        selected_group_ids = _unique_strings(
            assessment.get("group_ids"), f"{layer}.group_ids", failures
        )
        selected_fields = _unique_strings(
            assessment.get("composition_fields"),
            f"{layer}.composition_fields",
            failures,
        )
        selected_sequence_indexes = _unique_indexes(
            assessment.get("sequence_indexes"),
            f"{layer}.sequence_indexes",
            failures,
        )
        selected_assumption_indexes = _unique_indexes(
            assessment.get("assumption_indexes"),
            f"{layer}.assumption_indexes",
            failures,
        )
        reason = assessment.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            failures.append(f"{layer}.reason must be a non-empty string")

        raw_edges = assessment.get("edge_selectors")
        selected_edges: list[tuple[str, str, str]] = []
        if not isinstance(raw_edges, list):
            failures.append(f"{layer}.edge_selectors must be an array")
        else:
            for index, selector in enumerate(raw_edges):
                if not isinstance(selector, dict) or set(selector) != {
                    "source",
                    "target",
                    "label",
                }:
                    failures.append(
                        f"{layer}.edge_selectors[{index}] must contain exactly "
                        "source, target, and label"
                    )
                    continue
                triple = tuple(
                    selector.get(field) for field in ("source", "target", "label")
                )
                if not all(
                    isinstance(value, str) and value.strip() for value in triple
                ):
                    failures.append(
                        f"{layer}.edge_selectors[{index}] must use non-empty strings"
                    )
                    continue
                selected_edges.append(triple)  # type: ignore[arg-type]
            if len(selected_edges) != len(set(selected_edges)):
                failures.append(f"{layer}.edge_selectors must not contain duplicates")

        if any(node_id not in node_ids for node_id in selected_node_ids):
            failures.append(f"{layer}.node_ids contains an unknown node")
        if any(selector not in edge_selectors for selector in selected_edges):
            failures.append(f"{layer}.edge_selectors contains an edge absent from the graph")
        if any(group_id not in group_ids for group_id in selected_group_ids):
            failures.append(f"{layer}.group_ids contains an unknown group")
        if any(field not in COMPOSITION_FIELDS for field in selected_fields):
            failures.append(f"{layer}.composition_fields contains an unknown field")
        if any(
            index >= len(graph.get("sequence") or [])
            for index in selected_sequence_indexes
        ):
            failures.append(f"{layer}.sequence_indexes contains an unknown record")
        if any(
            index >= len(graph.get("assumptions") or [])
            for index in selected_assumption_indexes
        ):
            failures.append(f"{layer}.assumption_indexes contains an unknown record")

        irrelevant_values = {
            "components": (
                selected_edges,
                selected_group_ids,
                selected_fields,
                selected_sequence_indexes,
                selected_assumption_indexes,
            ),
            "connections": (
                selected_node_ids,
                selected_group_ids,
                selected_fields,
                selected_sequence_indexes,
                selected_assumption_indexes,
            ),
            "composition": (selected_node_ids, selected_edges),
            "render": (
                selected_node_ids,
                selected_edges,
                selected_group_ids,
                selected_fields,
                selected_sequence_indexes,
                selected_assumption_indexes,
            ),
        }[layer]
        if any(irrelevant_values):
            failures.append(
                f"{layer} assessment contains selectors owned by another layer"
            )
        if layer == "composition":
            if selected_group_ids and "groups" not in selected_fields:
                failures.append("composition.group_ids requires the groups field")
            if selected_sequence_indexes and "sequence" not in selected_fields:
                failures.append("composition.sequence_indexes requires the sequence field")
            if selected_assumption_indexes and "assumptions" not in selected_fields:
                failures.append(
                    "composition.assumption_indexes requires the assumptions field"
                )
            if status == "fail" and not selected_fields:
                failures.append("a failed composition layer must cite an editable field")

        if status == "fail":
            failed_layers.add(layer)
            if not findings:
                failures.append(f"{layer} fail status requires a blocking finding")
        else:
            if findings:
                failures.append(
                    f"{layer} {status} status cannot contain blocking findings"
                )
            if layer_deterministic_ids:
                failures.append(
                    f"{layer} {status} status cannot classify deterministic findings"
                )
            if any((
                selected_node_ids,
                selected_edges,
                selected_group_ids,
                selected_fields,
                selected_sequence_indexes,
                selected_assumption_indexes,
            )):
                failures.append(
                    f"{layer} {status} status cannot expose editable selectors"
                )
        if (
            status == "pass"
            and isinstance(score, (int, float))
            and score < APPROVAL_SCORE
        ):
            failures.append(f"{layer} pass score must be at least {APPROVAL_SCORE}")
        if (
            status == "fail"
            and isinstance(score, (int, float))
            and score >= APPROVAL_SCORE
        ):
            failures.append(f"{layer} fail score must be below {APPROVAL_SCORE}")
        all_findings.extend(findings)
        classified_deterministic_ids.extend(layer_deterministic_ids)

    if len(all_findings) != len(set(all_findings)):
        failures.append(
            "blocking findings must belong to one layer and must not be duplicated"
        )
    if len(classified_deterministic_ids) != len(set(classified_deterministic_ids)):
        failures.append("each deterministic finding ID must be classified exactly once")
    if (
        deterministic_finding_owners is not None
        and set(classified_deterministic_ids) != set(deterministic_finding_owners)
    ):
        failures.append("every supplied deterministic finding ID must be classified exactly once")
    if scope == "none" and failed_layers:
        failures.append("repair_scope none cannot contain a failed layer")
    if scope == "local":
        if not failed_layers.intersection({"components", "connections", "composition"}):
            failures.append("repair_scope local requires a failed editable graph layer")
    if scope == "global" and not failed_layers:
        failures.append("repair_scope global requires at least one failed layer")
    if scope != "none" and not failed_layers:
        failures.append("a repair scope requires a failed layer")
    if failures:
        raise ValueError("repair contract invalid: " + "; ".join(failures))
