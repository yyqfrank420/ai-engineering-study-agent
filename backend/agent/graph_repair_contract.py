from __future__ import annotations

import math
import re
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
    "context_node_ids",
    "addition_count",
    "connection_addition_obligations",
    "composition_append_counts",
}

_NEW_NODE_REFERENCE = re.compile(r"\$new_node_(?P<position>[1-9][0-9]*)")


class LocalRepairAdmissionError(ValueError):
    """A safe, stable coordinate for a rejected local repair contract."""

    def __init__(self, message: str, *, path: str, rule: str) -> None:
        super().__init__(message)
        self.path = path
        self.rule = rule


def requires_grouped_component_placement(
    graph: dict[str, Any], component_additions: int
) -> bool:
    """Return whether added components need exact group placement authority."""
    return component_additions > 0 and bool(graph.get("groups"))


def repair_scope_for_layers(layers: dict[str, Any]) -> str:
    """Derive repair scope from the layer ownership that grants mutation authority."""
    failed_layers = {
        layer
        for layer in REPAIR_LAYERS
        if isinstance(layers.get(layer), dict) and layers[layer].get("status") == "fail"
    }
    if not failed_layers:
        return "none"
    if failed_layers - {"render"}:
        return "local"
    return "global"


def validate_local_repair_admission(
    contract: dict[str, Any],
    *,
    graph: dict[str, Any],
) -> None:
    """Validate local record-scoped mutation authority before patching."""
    validate_repair_contract(contract, graph=graph)
    if contract["repair_scope"] != "local":
        raise LocalRepairAdmissionError(
            "only a local repair contract can enter the patch lane",
            path="repair_contract.repair_scope",
            rule="invalid_local_admission",
        )

    layers = contract["layers"]
    components = layers["components"]
    composition = layers["composition"]
    composition_fields = set(composition["composition_fields"])

    selector_fields = {
        "groups": "group_ids",
        "sequence": "sequence_indexes",
        "assumptions": "assumption_indexes",
    }
    composition_selectors = {
        field: composition[selector_field]
        for field, selector_field in selector_fields.items()
    }
    append_counts = composition["composition_append_counts"]
    for field, selectors in composition_selectors.items():
        if (
            field in composition_fields
            and not selectors
            and not append_counts.get(field)
        ):
            raise LocalRepairAdmissionError(
                f"local repair cannot replace the whole {field} collection",
                path=f"layers.composition.{selector_fields[field]}",
                rule="unbounded_collection",
            )
    context_node_ids = set(components["context_node_ids"]) | set(
        layers["connections"]["context_node_ids"]
    )
    if components["addition_count"] and not context_node_ids:
        raise LocalRepairAdmissionError(
            "local component additions require an existing graph anchor",
            path="layers.components.context_node_ids",
            rule="missing_graph_anchor",
        )
    if layers["connections"]["addition_count"] < components["addition_count"]:
        raise LocalRepairAdmissionError(
            "local additions require enough edges to attach every new component",
            path="layers.connections.addition_count",
            rule="insufficient_connection_additions",
        )
    if components["addition_count"]:
        new_node_ids = {
            f"$new_node_{position}"
            for position in range(1, components["addition_count"] + 1)
        }
        new_node_neighbors = {node_id: set() for node_id in new_node_ids}
        nodes_anchored_to_existing: set[str] = set()
        for obligation in layers["connections"]["connection_addition_obligations"]:
            source = obligation["source"]
            target = obligation["target"]
            if source in new_node_ids and target in new_node_ids:
                new_node_neighbors[source].add(target)
                new_node_neighbors[target].add(source)
            elif source in new_node_ids:
                nodes_anchored_to_existing.add(source)
            elif target in new_node_ids:
                nodes_anchored_to_existing.add(target)

        unseen = set(new_node_ids)
        while unseen:
            pending = {unseen.pop()}
            region: set[str] = set()
            while pending:
                node_id = pending.pop()
                region.add(node_id)
                neighbors = new_node_neighbors[node_id] & unseen
                unseen -= neighbors
                pending.update(neighbors)
            if region.isdisjoint(nodes_anchored_to_existing):
                raise LocalRepairAdmissionError(
                    "every new component region requires a connection to an existing graph node",
                    path="layers.connections.connection_addition_obligations",
                    rule="missing_graph_anchor",
                )


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
    addition_counts: dict[str, int] = {}
    connection_addition_obligations: list[dict[str, str]] = []
    composition_append_counts: dict[str, dict[str, int]] = {}
    for layer in REPAIR_LAYERS:
        assessment = layers.get(layer)
        if not isinstance(assessment, dict) or set(assessment) != _ASSESSMENT_FIELDS:
            failures.append(
                f"{layer} assessment must contain exactly the required fields"
            )
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
        context_node_ids = _unique_strings(
            assessment.get("context_node_ids"),
            f"{layer}.context_node_ids",
            failures,
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
        addition_count = assessment.get("addition_count")
        if (
            isinstance(addition_count, bool)
            or not isinstance(addition_count, int)
            or addition_count < 0
        ):
            failures.append(f"{layer}.addition_count must be a non-negative integer")
            addition_count = 0
        addition_counts[layer] = addition_count
        if layer not in {"components", "connections"} and addition_count:
            failures.append(f"{layer} cannot add graph records")
        raw_connection_obligations = assessment.get("connection_addition_obligations")
        parsed_connection_obligations: list[dict[str, str]] = []
        if not isinstance(raw_connection_obligations, list):
            failures.append(f"{layer}.connection_addition_obligations must be an array")
        else:
            for index, obligation in enumerate(raw_connection_obligations):
                if not isinstance(obligation, dict) or set(obligation) != {
                    "source",
                    "target",
                    "required_contract",
                }:
                    failures.append(
                        f"{layer}.connection_addition_obligations[{index}] must contain "
                        "exactly source, target, and required_contract"
                    )
                    continue
                if any(
                    not isinstance(obligation.get(field), str)
                    or not obligation[field].strip()
                    for field in ("source", "target", "required_contract")
                ):
                    failures.append(
                        f"{layer}.connection_addition_obligations[{index}] must use "
                        "non-empty strings"
                    )
                    continue
                if obligation["source"] == obligation["target"]:
                    failures.append(
                        f"{layer}.connection_addition_obligations[{index}] must use "
                        "distinct endpoints"
                    )
                    continue
                parsed_connection_obligations.append(obligation)
        obligation_keys = [
            (
                obligation["source"],
                obligation["target"],
                obligation["required_contract"],
            )
            for obligation in parsed_connection_obligations
        ]
        if len(obligation_keys) != len(set(obligation_keys)):
            failures.append(
                f"{layer}.connection_addition_obligations must not contain duplicates"
            )
        if layer == "connections":
            connection_addition_obligations = parsed_connection_obligations
            if addition_count != len(parsed_connection_obligations):
                failures.append(
                    "connections.addition_count must equal the number of exact "
                    "connection addition obligations"
                )
        elif parsed_connection_obligations:
            failures.append(f"{layer} cannot declare connection addition obligations")
        append_counts = assessment.get("composition_append_counts")
        if not isinstance(append_counts, dict) or any(
            field not in {"groups", "sequence", "assumptions"}
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            for field, count in (
                append_counts.items() if isinstance(append_counts, dict) else []
            )
        ):
            failures.append(
                f"{layer}.composition_append_counts must map composition fields to positive integers"
            )
            append_counts = {}
        composition_append_counts[layer] = append_counts
        if layer != "composition" and append_counts:
            failures.append(f"{layer} cannot append composition records")

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
        if any(node_id not in node_ids for node_id in context_node_ids):
            failures.append(f"{layer}.context_node_ids contains an unknown node")
        if any(selector not in edge_selectors for selector in selected_edges):
            failures.append(
                f"{layer}.edge_selectors contains an edge absent from the graph"
            )
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
                failures.append(
                    "composition.sequence_indexes requires the sequence field"
                )
            if selected_assumption_indexes and "assumptions" not in selected_fields:
                failures.append(
                    "composition.assumption_indexes requires the assumptions field"
                )
            if status == "fail" and scope == "local" and not selected_fields:
                failures.append(
                    "a failed composition layer must cite an editable field"
                )
            if any(field not in selected_fields for field in append_counts):
                failures.append(
                    "composition append counts require their editable composition fields"
                )
        if (
            layer == "components"
            and status == "fail"
            and scope == "local"
            and not selected_node_ids
            and addition_count == 0
        ):
            failures.append(
                "a failed components layer must cite a node or declare additions"
            )
        if (
            layer == "connections"
            and status == "fail"
            and scope == "local"
            and not selected_edges
            and addition_count == 0
        ):
            failures.append(
                "a failed connections layer must cite an edge or declare additions"
            )

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
            if any(
                (
                    selected_node_ids,
                    selected_edges,
                    selected_group_ids,
                    selected_fields,
                    selected_sequence_indexes,
                    selected_assumption_indexes,
                    context_node_ids,
                    parsed_connection_obligations,
                )
            ):
                failures.append(
                    f"{layer} {status} status cannot expose editable selectors"
                )
            if addition_count:
                failures.append(f"{layer} {status} status cannot add records")
            if append_counts:
                failures.append(
                    f"{layer} {status} status cannot append composition records"
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
    if deterministic_finding_owners is not None:
        unknown_deterministic_ids = set(classified_deterministic_ids) - set(
            deterministic_finding_owners
        )
        if unknown_deterministic_ids:
            failures.append("classified deterministic finding IDs must be supplied")
        if deterministic_finding_owners and not classified_deterministic_ids:
            failures.append(
                "the active repair region must classify a deterministic finding"
            )
    components = layers.get("components") if isinstance(layers, dict) else None
    connections = layers.get("connections") if isinstance(layers, dict) else None
    composition = layers.get("composition") if isinstance(layers, dict) else None
    component_additions = addition_counts.get("components", 0)
    connection_additions = addition_counts.get("connections", 0)
    allowed_new_node_references = {
        f"$new_node_{position}" for position in range(1, component_additions + 1)
    }
    obligation_endpoints = {
        endpoint
        for obligation in connection_addition_obligations
        for endpoint in (obligation["source"], obligation["target"])
    }
    unknown_obligation_endpoints = obligation_endpoints - (
        node_ids | allowed_new_node_references
    )
    if unknown_obligation_endpoints:
        failures.append("connection addition obligations contain an unknown endpoint")
    invalid_new_node_references = {
        endpoint
        for endpoint in obligation_endpoints
        if endpoint.startswith("$new_node_")
        and (
            not (match := _NEW_NODE_REFERENCE.fullmatch(endpoint))
            or int(match.group("position")) > component_additions
        )
    }
    if invalid_new_node_references:
        failures.append(
            "connection addition obligations contain an invalid new-node reference"
        )
    missing_new_node_references = allowed_new_node_references - obligation_endpoints
    if missing_new_node_references:
        failures.append(
            "every component addition must appear in a connection addition obligation"
        )
    if isinstance(components, dict) and component_additions > 0:
        if not (
            isinstance(connections, dict)
            and connections.get("status") == "fail"
            and connection_additions > 0
        ):
            failures.append(
                "component additions require connection addition permission"
            )
        if requires_grouped_component_placement(graph, component_additions) and not (
            isinstance(composition, dict)
            and composition.get("status") == "fail"
            and "groups" in (composition.get("composition_fields") or [])
        ):
            failures.append(
                "component additions in a grouped graph require editable groups"
            )
        elif requires_grouped_component_placement(graph, component_additions) and not (
            composition.get("group_ids")
            or composition_append_counts.get("composition", {}).get("groups", 0)
        ):
            failures.append(
                "component additions in a grouped graph require an editable existing group or a declared group append"
            )
    if connection_additions > 0:
        connection_context = set(
            connections.get("context_node_ids", [])
            if isinstance(connections, dict)
            else []
        )
        component_context = set(
            components.get("context_node_ids", [])
            if isinstance(components, dict)
            else []
        )
        available_endpoint_count = component_additions + len(
            connection_context | component_context
        )
        if available_endpoint_count < 2:
            failures.append(
                "connection additions require at least two declared endpoint identities"
            )
        existing_obligation_endpoints = obligation_endpoints & node_ids
        if not existing_obligation_endpoints.issubset(
            connection_context | component_context
        ):
            failures.append(
                "connection addition obligation endpoints must be declared as context nodes"
            )
    if scope in {"none", "local", "global"} and isinstance(layers, dict):
        derived_scope = repair_scope_for_layers(layers)
        if scope != derived_scope:
            failures.append(
                f"repair_scope must be {derived_scope} for the failed layer ownership"
            )
    if failures:
        raise ValueError("repair contract invalid: " + "; ".join(failures))
