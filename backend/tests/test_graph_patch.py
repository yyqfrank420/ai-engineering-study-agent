import copy
import json
from types import SimpleNamespace

import pytest
from agent.complexity import resolve_complexity
from agent.graph_repair_contract import validate_local_repair_admission
from agent.nodes import graph_worker


def test_patch_accepts_multiple_operations_while_preserving_existing_records():
    graph = _domain_graph(5)
    patch = {
        "update_nodes": [
            {
                "id": node["id"],
                "set": {"description": f"Keeps bounded responsibility {index}."},
            }
            for index, node in enumerate(graph["nodes"][:-1])
        ],
        "update_edges": [
            {
                "edge_id": f"edge_{index}",
                "set": {"description": f"Keeps bounded transition {index}."},
            }
            for index, _edge in enumerate(graph["edges"][:-1], start=1)
        ],
    }

    result = graph_worker._apply_applied_graph_patch(
        graph,
        patch,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(result["nodes"]) == 5
    assert len(result["edges"]) == 5


@pytest.mark.parametrize("record_type", ["node", "edge"])
def test_patch_rejects_noop_updates_even_with_another_real_change(record_type):
    graph = _domain_graph(5)
    if record_type == "node":
        patch = {
            "update_nodes": [
                {
                    "id": graph["nodes"][0]["id"],
                    "set": {"label": graph["nodes"][0]["label"]},
                },
                {
                    "id": graph["nodes"][1]["id"],
                    "set": {"description": "A valid separate node change."},
                },
            ]
        }
    else:
        patch = {
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {"label": graph["edges"][0]["label"]},
                },
                {
                    "edge_id": "edge_2",
                    "set": {"description": "A valid separate edge change."},
                },
            ]
        }

    with pytest.raises(
        ValueError, match=f"{record_type} update produced no semantic change"
    ):
        graph_worker._apply_applied_graph_patch(
            graph,
            patch,
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_graph_design_json_failure_is_classified_as_truncated():
    exc = json.JSONDecodeError("Unterminated string", "{", 1)

    assert (
        graph_worker._graph_design_failure_code(exc) == "graph_design_output_truncated"
    )


def test_graph_timeouts_and_invalid_patches_have_distinct_failure_codes():
    assert (
        graph_worker._graph_design_failure_code(TimeoutError("deadline exhausted"))
        == "graph_design_timeout"
    )
    assert (
        graph_worker._graph_patch_failure_code(TimeoutError("deadline exhausted"))
        == "graph_patch_timeout_preserved_existing_graph"
    )
    assert (
        graph_worker._graph_patch_failure_code(ValueError("unknown graph patch field"))
        == "graph_patch_invalid_preserved_existing_graph"
    )


def test_repair_feedback_preserves_every_known_blocker():
    review = {
        "approved": False,
        "missing": ["first blocker", "second blocker", "residual blocker"],
        "revision_instruction": "repair everything",
    }

    complete = graph_worker._repair_review(review)

    assert complete["missing"] == review["missing"]
    assert complete["revision_instruction"] == "repair everything"


def test_topology_builder_delegates_size_to_material_design():
    contract = graph_worker._APPLIED_GRAPH_TOPOLOGY_SYSTEM

    assert "Choose graph size from the material design" in contract
    assert "trust boundaries" in contract
    assert "failure outcomes" in contract
    assert "9 nodes" not in contract


def test_patch_topology_context_exposes_only_contract_owned_mutable_detail():
    graph = {
        "title": "Bounded graph",
        "assumptions": ["The policy store supports version reads."],
        "groups": [{"id": "runtime"}],
        "sequence": [{"step": 1, "nodes": ["gate"], "description": "Review."}],
        "nodes": [
            {
                "id": "gate",
                "label": "Approval Gate",
                "type": "decision",
                "description": "Routes approved and rejected outcomes.",
                "technology": "Policy rules engine",
            },
            {
                "id": "ledger",
                "label": "Decision Ledger",
                "type": "datastore",
                "description": "Persists the decision.",
                "technology": "PostgreSQL",
            },
            {
                "id": "observer",
                "label": "Outcome Observer",
                "type": "service",
                "description": "Reads terminal outcomes.",
                "technology": "Worker",
            },
        ],
        "edges": [
            {
                "source": "gate",
                "target": "ledger",
                "label": "persist rejection",
                "flow": "control",
                "sync": "async",
                "type": "loop",
                "description": "Durable terminal outcome.",
                "technology": "Signed decision record",
            },
            {
                "source": "ledger",
                "target": "observer",
                "label": "publish outcome",
                "flow": "runtime",
                "sync": "async",
                "description": "Publishes a terminal state.",
                "technology": "Outbox event",
            },
        ],
    }
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "edge_selectors": [
                    {
                        "source": "gate",
                        "target": "ledger",
                        "label": "persist rejection",
                    }
                ]
            },
            "composition": {
                "composition_fields": ["assumptions"],
                "assumption_indexes": [0],
            },
        }
    )
    context = json.loads(graph_worker._format_patch_topology(graph, contract))

    assert set(context) == {"nodes", "edges", "assumptions"}
    assert context["assumptions"] == ["The policy store supports version reads."]
    assert set(context["nodes"][0]) == {
        "id",
        *graph_worker._PATCH_NODE_MUTABLE_FIELDS,
    }
    assert set(context["nodes"][1]) == {
        "id",
        *graph_worker._PATCH_NODE_MUTABLE_FIELDS,
    }
    assert set(context["nodes"][2]) == {"id", "label", "type"}
    assert set(context["edges"][0]) == {
        "edge_id",
        *graph_worker._PATCH_EDGE_MUTABLE_FIELDS,
    }
    assert set(context["edges"][1]) == {
        "edge_id",
        "source",
        "target",
        "label",
        "sync",
        "flow",
    }
    assert context["nodes"][0]["technology"] == "Policy rules engine"
    assert context["nodes"][0]["description"] == (
        "Routes approved and rejected outcomes."
    )
    assert context["edges"][0]["technology"] == "Signed decision record"
    assert context["edges"][0]["description"] == "Durable terminal outcome."
    assert context["edges"][0]["edge_id"] == "edge_1"
    assert context["edges"][1]["edge_id"] == "edge_2"
    assert "Outbox event" not in json.dumps(context)


def _domain_graph(node_count: int, *, production: bool = False) -> dict:
    nodes = [
        {
            "id": f"fulfilment_stage_{index}",
            "label": f"Fulfilment Stage {index}",
            "type": "service",
            "technology": "Bounded domain capability",
            "description": "Owns one explicit marketplace fulfilment responsibility.",
            "tier": "private",
            "lane": "main",
        }
        for index in range(node_count)
    ]
    edges = [
        {
            "source": f"fulfilment_stage_{index}",
            "target": f"fulfilment_stage_{index + 1}",
            "label": f"passes verified parcel state {index}",
            "technology": "Versioned domain event",
            "sync": "async",
            "flow": "runtime",
            "description": "Moves verified parcel state to the next bounded responsibility.",
        }
        for index in range(node_count - 1)
    ]
    edges.append(
        {
            "source": f"fulfilment_stage_{node_count - 1}",
            "target": "fulfilment_stage_0",
            "label": "returns measured delivery outcome",
            "technology": "Outcome event",
            "sync": "async",
            "flow": "feedback",
            "type": "loop",
            "description": "Closes the marketplace fulfilment feedback loop.",
        }
    )
    groups = []
    sequence = []
    if production:
        groups = [
            {
                "id": "intake",
                "label": "Marketplace Intake",
                "kind": "runtime",
                "nodeIds": [f"fulfilment_stage_{index}" for index in range(3)],
            },
            {
                "id": "execution",
                "label": "Fulfilment Execution",
                "kind": "runtime",
                "nodeIds": [f"fulfilment_stage_{index}" for index in range(3, 6)],
            },
            {
                "id": "outcomes",
                "label": "Outcome Controls",
                "kind": "operations",
                "nodeIds": [
                    f"fulfilment_stage_{index}" for index in range(6, node_count)
                ],
            },
        ]
        sequence = [
            {
                "step": index + 1,
                "nodes": [f"fulfilment_stage_{index}"],
                "description": f"Runs observable marketplace step {index + 1}.",
            }
            for index in range(4)
        ]
    return graph_worker._normalise_applied_graph(
        {
            "title": "Marketplace fulfilment control loop",
            "assumptions": ["Carriers publish durable parcel events."],
            "nodes": nodes,
            "edges": edges,
            "groups": groups,
            "sequence": sequence,
        },
        safety_max_nodes=node_count,
        resolved_complexity="production" if production else "prototype",
    )


def _layer(status="pass", *, findings=None, **selectors):
    return {
        "status": status,
        "score": 0.7 if status == "fail" else 0.9,
        "blocking_findings": list(findings or []),
        "deterministic_finding_ids": [],
        "node_ids": list(selectors.get("node_ids") or []),
        "edge_selectors": list(selectors.get("edge_selectors") or []),
        "group_ids": list(selectors.get("group_ids") or []),
        "composition_fields": list(selectors.get("composition_fields") or []),
        "sequence_indexes": list(selectors.get("sequence_indexes") or []),
        "assumption_indexes": list(selectors.get("assumption_indexes") or []),
        "context_node_ids": list(selectors.get("context_node_ids") or []),
        "addition_count": int(selectors.get("addition_count", 0)),
        "connection_addition_obligations": list(
            selectors.get("connection_addition_obligations") or []
        ),
        "composition_append_counts": dict(
            selectors.get("composition_append_counts") or {}
        ),
        "reason": "The layer was assessed against the requested architecture.",
    }


def _local_repair_contract(*, failed_layers):
    layers = {
        layer: _layer()
        for layer in ("components", "connections", "composition", "render")
    }
    for layer, selectors in failed_layers.items():
        layers[layer] = _layer(
            "fail",
            findings=[f"Repair the {layer} layer."],
            **selectors,
        )
    connections = layers["connections"]
    if (
        connections["addition_count"]
        and not connections["connection_addition_obligations"]
    ):
        components = layers["components"]
        anchors = (
            connections["context_node_ids"]
            or components["context_node_ids"]
            or components["node_ids"]
        )
        obligations = []
        for position in range(1, connections["addition_count"] + 1):
            if position <= components["addition_count"] and anchors:
                source, target = anchors[0], f"$new_node_{position}"
            elif len(anchors) >= 2:
                source, target = anchors[0], anchors[1]
            elif anchors and components["addition_count"]:
                source, target = "$new_node_1", anchors[0]
            else:
                break
            obligations.append(
                {
                    "source": source,
                    "target": target,
                    "required_contract": f"Apply connection repair {position}.",
                }
            )
        connections["connection_addition_obligations"] = obligations
    return {"repair_scope": "local", "layers": layers}


def test_repair_context_defines_only_failed_rubric_and_proof_requirements():
    contract = _local_repair_contract(
        failed_layers={"connections": {"addition_count": 1}}
    )
    contract["layers"]["connections"]["blocking_findings"] = [
        "Repair state order integrity in the connections layer.",
        "Repair the failed state effect reconciliation topology proof in the connections layer.",
    ]

    context = graph_worker._repair_review(
        {
            "repair_contract": contract,
            "topology_proofs": [
                {
                    "guarantee": "state_effect_reconciliation",
                    "status": "fail",
                }
            ],
        }
    )

    assert context["repair_contract"] == contract
    requirements = context["repair_requirements"]
    assert [item["criterion"] for item in requirements] == [
        "state_order_integrity",
        "topology_proof:state_effect_reconciliation",
    ]
    assert "Split lookup/write" in requirements[0]["requirement"]
    assert "durable operation reservation" in requirements[1]["requirement"]
    assert "complete_reconciliation" not in json.dumps(requirements)


def test_component_addition_treats_technology_and_group_names_as_modifiers():
    prototype = _domain_graph(5)
    prototype_contract, prototype_permissions = graph_worker._user_edit_scope(
        "Add PostgreSQL database connected to Fulfilment Stage 1",
        prototype,
        resolved_complexity="prototype",
    )

    assert prototype_contract["layers"]["components"]["addition_count"] == 1
    assert prototype_contract["layers"]["connections"]["addition_count"] == 1
    assert prototype_permissions["allowed_new_node_ids"] == ["postgresql_database"]
    assert prototype_permissions["added_edge_anchor_node_ids"] == ["fulfilment_stage_1"]

    production = _domain_graph(9, production=True)
    production_contract, production_permissions = graph_worker._user_edit_scope(
        (
            "Add Prometheus connected to Fulfilment Stage 7 in the "
            "Outcome Controls group"
        ),
        production,
        resolved_complexity="production",
    )

    composition = production_contract["layers"]["composition"]
    assert composition["group_ids"] == ["outcomes"]
    assert composition["composition_append_counts"] == {}
    assert production_permissions["composition_append_limits"] == {"groups": 0}


@pytest.mark.parametrize(
    ("message", "component_id"),
    [
        (
            "Add Route Planner connected to Fulfilment Stage 1",
            "route_planner",
        ),
        (
            "Add Sequence Planner connected to Fulfilment Stage 1",
            "sequence_planner",
        ),
        (
            "Add Prometheus and link it to Fulfilment Stage 1",
            "prometheus",
        ),
        ("Add Prometheus to Fulfilment Stage 1", "prometheus"),
        ("Include Prometheus linked to Fulfilment Stage 1", "prometheus"),
        ("Add Prometheus connecting to Fulfilment Stage 1", "prometheus"),
        ("Add Prometheus and attach it to Fulfilment Stage 1", "prometheus"),
        ("Add Prometheus connected with Fulfilment Stage 1", "prometheus"),
    ],
)
def test_component_addition_identity_is_independent_of_reserved_words_and_phrasing(
    message,
    component_id,
):
    contract, permissions = graph_worker._user_edit_scope(
        message,
        _domain_graph(5),
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["addition_count"] == 1
    assert contract["layers"]["connections"]["addition_count"] == 1
    assert permissions["allowed_new_node_ids"] == [component_id]
    assert permissions["added_edge_anchor_node_ids"] == ["fulfilment_stage_1"]


@pytest.mark.parametrize(
    "message",
    [
        "Add a cache and a queue connected to Gateway",
        "Add cache connected to Gateway and queue connected to Gateway",
    ],
)
def test_component_addition_rejects_multi_add_syntax(message):
    graph = _domain_graph(5)
    graph["nodes"][0]["label"] = "Gateway"

    with pytest.raises(ValueError, match="component addition"):
        graph_worker._user_edit_scope(
            message,
            graph,
            resolved_complexity="prototype",
        )


@pytest.mark.parametrize(
    ("message", "field"),
    [
        ("Remove Cache Link", None),
        ("Rename Sequence Planner to Workflow Planner", "label"),
    ],
)
def test_existing_component_names_do_not_grant_other_layer_authority(message, field):
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Cache Link" if field is None else "Sequence Planner"

    contract, permissions = graph_worker._user_edit_scope(
        message,
        graph,
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["node_ids"] == ["fulfilment_stage_1"]
    assert contract["layers"]["composition"]["status"] == "pass"
    assert permissions["allow_node_additions"] is False
    assert permissions["allow_edge_additions"] is False
    if field is None:
        assert permissions["removable_node_ids"] == ["fulfilment_stage_1"]
    else:
        assert permissions["editable_node_fields"] == {"fulfilment_stage_1": [field]}


def test_longest_authored_name_owns_a_contained_reference():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Cache"
    graph["nodes"][2]["label"] = "Cache Link"

    contract, permissions = graph_worker._user_edit_scope(
        "Remove Cache Link",
        graph,
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["node_ids"] == ["fulfilment_stage_2"]
    assert permissions["removable_node_ids"] == ["fulfilment_stage_2"]
    assert {
        (edge["source"], edge["target"]) for edge in permissions["editable_edges"]
    } == {
        ("fulfilment_stage_1", "fulfilment_stage_2"),
        ("fulfilment_stage_2", "fulfilment_stage_3"),
    }


def test_direct_endpoint_only_connection_edit_rejects_parallel_edges():
    graph = _domain_graph(5)
    graph["edges"].append(
        {**copy.deepcopy(graph["edges"][0]), "label": "parallel state route"}
    )

    with pytest.raises(ValueError, match="matches multiple edges"):
        graph_worker._user_edit_scope(
            "Remove the connection from Fulfilment Stage 0 to Fulfilment Stage 1",
            graph,
            resolved_complexity="prototype",
        )

    _contract, permissions = graph_worker._user_edit_scope(
        "Remove edge_6 from Fulfilment Stage 0 to Fulfilment Stage 1",
        graph,
        resolved_complexity="prototype",
    )

    assert permissions["removable_edge_ids"] == ["edge_6"]
    with pytest.raises(ValueError, match="exact edge ID is not present"):
        graph_worker._user_edit_scope(
            "Remove edge_99 from Fulfilment Stage 0 to Fulfilment Stage 1",
            graph,
            resolved_complexity="prototype",
        )
    with pytest.raises(ValueError, match="exact edge ID is not present"):
        graph_worker._user_edit_scope(
            "Remove edge_1 and edge_99",
            graph,
            resolved_complexity="prototype",
        )


def test_endpoint_qualified_label_edit_cannot_select_unrelated_same_label_edges():
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = "shared transition"
    graph["edges"][2]["label"] = "shared transition"

    _contract, permissions = graph_worker._user_edit_scope(
        "Change the shared transition connection label from Fulfilment Stage 0 to Fulfilment Stage 1",
        graph,
        resolved_complexity="prototype",
    )

    assert [edge["edge_id"] for edge in permissions["editable_edges"]] == ["edge_1"]


def test_critic_selected_edge_cannot_change_endpoints():
    existing = _domain_graph(5)
    selected = {
        field: existing["edges"][0][field] for field in ("source", "target", "label")
    }
    contract = _local_repair_contract(
        failed_layers={"connections": {"edge_selectors": [selected]}}
    )

    with pytest.raises(ValueError, match="locked edge fields: source, target"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "update_edges": [
                    {
                        "edge_id": "edge_1",
                        "set": {
                            "source": "fulfilment_stage_4",
                            "target": "fulfilment_stage_0",
                        },
                    }
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_can_replace_a_selected_edge_only_through_an_exact_obligation():
    existing = _domain_graph(5)
    selected = {
        field: existing["edges"][0][field] for field in ("source", "target", "label")
    }
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "edge_selectors": [selected],
                "context_node_ids": ["fulfilment_stage_4", "fulfilment_stage_0"],
                "addition_count": 1,
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_4",
                        "target": "fulfilment_stage_0",
                        "required_contract": "replaces the intake route",
                    }
                ],
            }
        }
    )

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "remove_edges": ["edge_1"],
            "add_edges": [
                {
                    "source": "fulfilment_stage_4",
                    "target": "fulfilment_stage_0",
                    "label": "replaces the intake route",
                    "technology": "Typed event",
                    "sync": "async",
                    "flow": "runtime",
                    "description": "Replaces the selected route.",
                }
            ],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert all(edge["label"] != selected["label"] for edge in updated["edges"])
    assert any(
        edge["label"] == "replaces the intake route" for edge in updated["edges"]
    )


def test_critic_added_edge_label_matches_the_normalized_exact_obligation():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "context_node_ids": ["fulfilment_stage_0", "fulfilment_stage_2"],
                "addition_count": 1,
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "fulfilment_stage_2",
                        "required_contract": "adds verified route",
                    }
                ],
            }
        }
    )
    edge = {
        "source": "fulfilment_stage_0",
        "target": "fulfilment_stage_2",
        "label": " adds   verified route ",
        "technology": "Typed event",
        "sync": "async",
        "flow": "runtime",
        "description": "Adds the verified route.",
    }

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {"add_edges": [edge]},
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert updated["edges"][-1]["label"] == "adds verified route"
    with pytest.raises(ValueError, match="labels do not match"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {"add_edges": [{**edge, "label": "adds unrelated route"}]},
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_added_edge_label_cannot_be_swapped_between_obligation_pairs():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "context_node_ids": [
                    "fulfilment_stage_0",
                    "fulfilment_stage_2",
                    "fulfilment_stage_4",
                ],
                "addition_count": 2,
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "fulfilment_stage_2",
                        "required_contract": "first required route",
                    },
                    {
                        "source": "fulfilment_stage_2",
                        "target": "fulfilment_stage_4",
                        "required_contract": "second required route",
                    },
                ],
            }
        }
    )

    with pytest.raises(ValueError, match="labels do not match"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "add_edges": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "fulfilment_stage_2",
                        "label": "second required route",
                        "technology": "Typed event",
                        "sync": "async",
                        "flow": "runtime",
                        "description": "Adds the first required route.",
                    },
                    {
                        "source": "fulfilment_stage_2",
                        "target": "fulfilment_stage_4",
                        "label": "first required route",
                        "technology": "Typed event",
                        "sync": "async",
                        "flow": "runtime",
                        "description": "Adds the second required route.",
                    },
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_new_component_words_do_not_become_existing_connection_anchors():
    graph = _domain_graph(5)
    graph["nodes"][0]["label"] = "Gateway"
    graph["nodes"][1]["label"] = "Cache"
    graph["nodes"][2]["label"] = "Cache"

    _contract, permissions = graph_worker._user_edit_scope(
        "Add Cache Observer connected to Gateway",
        graph,
        resolved_complexity="prototype",
    )

    assert permissions["allowed_new_node_ids"] == ["cache_observer"]
    assert permissions["added_edge_anchor_node_ids"] == ["fulfilment_stage_0"]


def test_unique_broad_expansion_compiles_one_child_and_one_directed_edge():
    graph = _domain_graph(5)
    graph["nodes"][2]["label"] = "Drift & Quality Monitor"

    contract, permissions = graph_worker._user_edit_scope(
        (
            "Expand the monitoring component while preserving the original "
            "graph topic and existing components. Add exactly one directly "
            "connected responsibility."
        ),
        graph,
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["addition_count"] == 1
    assert contract["layers"]["components"]["node_ids"] == []
    assert contract["layers"]["connections"]["connection_addition_obligations"] == [
        {
            "source": "fulfilment_stage_2",
            "target": "$new_node_1",
            "required_contract": (
                "Add one directly connected responsibility that expands only "
                "the named component."
            ),
        }
    ]
    assert permissions["allowed_new_node_ids"] is None
    assert permissions["editable_node_ids"] == []
    assert permissions["allowed_new_node_count"] == 1
    assert permissions["allowed_new_edge_count"] == 1


def test_expansion_prefers_an_exact_token_match_over_a_broader_component_name():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Monitoring"
    graph["nodes"][2]["label"] = "Monitoring Alerts"

    target = graph_worker._scoped_expansion_target(
        "expand the monitoring component while preserving existing components.",
        graph["nodes"],
    )

    assert target == "fulfilment_stage_1"


def test_expansion_prefers_a_stemmed_exact_token_match_over_a_broader_match():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Monitor"
    graph["nodes"][2]["label"] = "Monitor Alerts"

    target = graph_worker._scoped_expansion_target(
        "expand the monitoring component while preserving existing components.",
        graph["nodes"],
    )

    assert target == "fulfilment_stage_1"


def test_expansion_rejects_multiple_broader_token_matches_without_an_exact_match():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Model Monitoring Gateway"
    graph["nodes"][2]["label"] = "Model Monitoring Archive"

    with pytest.raises(ValueError, match="exactly one authored component"):
        graph_worker._scoped_expansion_target(
            "expand model monitoring while preserving existing components.",
            graph["nodes"],
        )


def test_expansion_rejects_duplicate_exact_token_matches():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Monitoring"
    graph["nodes"][2]["label"] = "Monitoring"

    with pytest.raises(ValueError, match="more than one authored record"):
        graph_worker._scoped_expansion_target(
            "expand the monitoring component while preserving existing components.",
            graph["nodes"],
        )


def test_expansion_token_matching_keeps_stemming_for_broader_component_names():
    graph = _domain_graph(5)
    graph["nodes"][2]["label"] = "Drift & Quality Monitor"

    target = graph_worker._scoped_expansion_target(
        "expand the monitoring component while preserving existing components.",
        graph["nodes"],
    )

    assert target == "fulfilment_stage_2"


def test_production_expansion_without_groups_authorizes_one_new_group():
    graph = _domain_graph(5)
    graph["nodes"][2]["label"] = "Drift & Quality Monitor"

    contract, permissions = graph_worker._user_edit_scope(
        "Expand the monitoring component while preserving existing components.",
        graph,
        resolved_complexity="production",
    )

    composition = contract["layers"]["composition"]
    assert composition["composition_fields"] == ["groups"]
    assert composition["group_ids"] == []
    assert composition["composition_append_counts"] == {"groups": 1}
    assert permissions["allowed_new_group_ids"] is None
    assert permissions["composition_append_limits"] == {"groups": 1}


@pytest.mark.parametrize(
    "message",
    [
        "Expand the observability component while preserving the graph.",
        "Expand Fulfilment Stage 1 and Fulfilment Stage 2 components.",
    ],
)
def test_broad_expansion_requires_one_resolved_existing_target(message):
    with pytest.raises(ValueError, match="expansion"):
        graph_worker._user_edit_scope(
            message,
            _domain_graph(5),
            resolved_complexity="prototype",
        )


@pytest.mark.asyncio
async def test_unique_broad_expansion_preserves_existing_records(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][2]["label"] = "Drift & Quality Monitor"
    before = copy.deepcopy(existing)
    message = (
        "Expand the monitoring component while preserving the original graph "
        "topic and existing components. Add exactly one directly connected "
        "responsibility."
    )

    updated = await _run_first_turn_patch(
        monkeypatch,
        existing,
        message,
        {
            "add_nodes": [
                {
                    "id": "model_drift_alerts",
                    "label": "Model Drift Alerts",
                    "type": "service",
                    "technology": "Alert policy",
                    "description": "Owns actionable drift threshold notifications.",
                }
            ],
            "add_edges": [
                {
                    "source": "fulfilment_stage_2",
                    "target": "model_drift_alerts",
                    "label": "emits threshold breach",
                    "technology": "Versioned alert event",
                    "sync": "async",
                    "flow": "control",
                    "description": "Routes a measured breach to its alert owner.",
                }
            ],
        },
    )

    assert updated["nodes"][:-1] == before["nodes"]
    assert updated["edges"][:-1] == before["edges"]
    assert updated["nodes"][-1]["id"] == "model_drift_alerts"
    assert updated["title"] == before["title"]


def test_duplicate_authored_names_are_ambiguous():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Payment Service"
    graph["nodes"][2]["label"] = "Payment Service"

    with pytest.raises(ValueError, match="more than one authored record"):
        graph_worker._user_edit_scope(
            "Rename Payment Service to Billing Service",
            graph,
            resolved_complexity="prototype",
        )


def test_production_component_addition_uses_one_named_or_anchor_group():
    graph = _domain_graph(9, production=True)

    anchored_contract, anchored_permissions = graph_worker._user_edit_scope(
        "Add Prometheus connected to Fulfilment Stage 1",
        graph,
        resolved_complexity="production",
    )
    named_contract, named_permissions = graph_worker._user_edit_scope(
        (
            "Add Prometheus in the Outcome Controls group connected to "
            "Fulfilment Stage 7"
        ),
        graph,
        resolved_complexity="production",
    )

    assert anchored_contract["layers"]["composition"]["group_ids"] == ["intake"]
    assert anchored_permissions["composition_append_limits"] == {"groups": 0}
    assert named_contract["layers"]["composition"]["group_ids"] == ["outcomes"]
    assert named_permissions["allowed_new_node_ids"] == ["prometheus"]
    assert named_permissions["composition_append_limits"] == {"groups": 0}


def test_prototype_component_addition_requires_existing_group_placement():
    graph = _domain_graph(5)
    graph["groups"] = [
        {
            "id": "runtime",
            "label": "Runtime",
            "kind": "runtime",
            "nodeIds": [node["id"] for node in graph["nodes"]],
        }
    ]
    contract, permissions = graph_worker._user_edit_scope(
        "Add Prometheus connected to Fulfilment Stage 1",
        graph,
        resolved_complexity="prototype",
    )

    assert contract["layers"]["composition"]["status"] == "fail"
    assert contract["layers"]["composition"]["group_ids"] == ["runtime"]
    assert permissions["composition_append_limits"] == {"groups": 0}
    with pytest.raises(ValueError, match="complete groups replacement"):
        graph_worker._apply_applied_graph_patch(
            graph,
            {
                "add_nodes": [
                    {
                        "id": "prometheus",
                        "label": "Prometheus",
                        "type": "service",
                        "technology": "Prometheus",
                        "description": "Collects runtime metrics.",
                    }
                ],
                "add_edges": [
                    {
                        "source": "fulfilment_stage_1",
                        "target": "prometheus",
                        "label": "exports runtime metrics",
                        "technology": "Prometheus scrape protocol",
                        "sync": "async",
                        "flow": "control",
                        "description": "Exports bounded runtime measurements.",
                    }
                ],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
            mutation_permissions=permissions,
        )


def test_component_addition_rejects_an_existing_authored_name():
    graph = _domain_graph(5)
    graph["nodes"][1]["label"] = "Sequence Planner"

    with pytest.raises(ValueError, match="component identity already exists"):
        graph_worker._user_edit_scope(
            "Add Sequence Planner connected to Fulfilment Stage 2",
            graph,
            resolved_complexity="prototype",
        )


@pytest.mark.parametrize(
    ("message", "field"),
    [
        ("Add an assumption that alerts go to Fulfilment Stage 1", "assumptions"),
        ("Add a Monitoring group", "groups"),
        ("Add Monitoring group", "groups"),
    ],
)
def test_composition_addition_owns_its_record_despite_reserved_words(
    message,
    field,
):
    contract, permissions = graph_worker._user_edit_scope(
        message,
        _domain_graph(5),
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["status"] == "pass"
    assert contract["layers"]["connections"]["status"] == "pass"
    assert contract["layers"]["composition"]["composition_fields"] == [field]
    assert permissions["composition_append_limits"] == {field: 1}


def test_assumption_content_cannot_grant_connection_authority():
    contract, permissions = graph_worker._user_edit_scope(
        (
            "Add an assumption that Fulfilment Stage 1 connects to "
            "Fulfilment Stage 3 through the vendor network"
        ),
        _domain_graph(5),
        resolved_complexity="prototype",
    )

    assert contract["layers"]["connections"]["status"] == "pass"
    assert contract["layers"]["composition"]["composition_fields"] == ["assumptions"]
    assert permissions["allow_edge_additions"] is False
    assert permissions["editable_edges"] == []


def test_named_group_addition_rejects_a_different_group_identity():
    graph = _domain_graph(5)
    contract, permissions = graph_worker._user_edit_scope(
        "Add a Monitoring group",
        graph,
        resolved_complexity="prototype",
    )

    with pytest.raises(ValueError, match="group identities do not match"):
        graph_worker._apply_applied_graph_patch(
            graph,
            {
                "groups": [
                    {
                        "id": "operations",
                        "label": "Operations",
                        "kind": "runtime",
                        "nodeIds": [node["id"] for node in graph["nodes"]],
                    }
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
            mutation_permissions=permissions,
        )


def test_named_group_addition_never_requires_a_component_addition():
    contract, permissions = graph_worker._user_edit_scope(
        "Add Monitoring group for Fulfilment Stage 1",
        _domain_graph(5),
        resolved_complexity="prototype",
    )

    assert contract["layers"]["components"]["status"] == "pass"
    assert permissions["allowed_new_node_ids"] == []
    assert permissions["allowed_new_node_count"] == 0
    assert permissions["allowed_new_group_ids"] == ["monitoring"]


def test_hardest_branch_return_patch_bypasses_write_gate_and_preserves_eval_harness():
    existing = _domain_graph(5)
    renamed_ids = {
        "fulfilment_stage_0": "user_request",
        "fulfilment_stage_1": "fixed_workflow_orchestrator",
        "fulfilment_stage_2": "bounded_agent_loop",
        "fulfilment_stage_3": "write_confirmation_gate",
        "fulfilment_stage_4": "eval_regression_harness",
    }
    for node in existing["nodes"]:
        node["id"] = renamed_ids[node["id"]]
    for edge in existing["edges"]:
        edge["source"] = renamed_ids[edge["source"]]
        edge["target"] = renamed_ids[edge["target"]]
    existing = graph_worker._normalise_applied_graph(
        existing,
        safety_max_nodes=5,
        resolved_complexity="prototype",
    )
    before = copy.deepcopy(existing)
    branch_edges = [
        {
            "source": "fixed_workflow_orchestrator",
            "target": "user_request",
            "label": "returns completed workflow response",
            "technology": "Streaming response",
            "sync": "async",
            "flow": "runtime",
            "description": "Completes read-only workflows without entering the write-only gate.",
        },
        {
            "source": "bounded_agent_loop",
            "target": "user_request",
            "label": "returns completed agent response",
            "technology": "Streaming response",
            "sync": "async",
            "flow": "runtime",
            "description": "Completes advisory agent work without entering the write-only gate.",
        },
    ]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {"add_edges": branch_edges},
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert existing == before
    assert [node["id"] for node in result["nodes"]] == [
        node["id"] for node in before["nodes"]
    ]
    assert len(result["edges"]) == len(before["edges"]) + 2
    assert {
        (edge["source"], edge["target"])
        for edge in result["edges"]
        if edge["target"] == "user_request"
    } >= {
        ("fixed_workflow_orchestrator", "user_request"),
        ("bounded_agent_loop", "user_request"),
    }
    assert next(
        node for node in result["nodes"] if node["id"] == "eval_regression_harness"
    ) == next(
        node for node in before["nodes"] if node["id"] == "eval_regression_harness"
    )
    assert any(
        edge["source"] == "write_confirmation_gate"
        and edge["target"] == "eval_regression_harness"
        for edge in result["edges"]
    )


def test_cache_node_patch_preserves_unrelated_production_graph_out_of_sample():
    existing = _domain_graph(9, production=True)
    before = copy.deepcopy(existing)
    groups = copy.deepcopy(existing["groups"])
    groups[1]["nodeIds"].append("carrier_quote_cache")
    patch = {
        "add_nodes": [
            {
                "id": "carrier_quote_cache",
                "label": "Carrier Quote Cache",
                "type": "datastore",
                "technology": "Bounded TTL key-value cache",
                "description": "Reuses fresh carrier quotes while preserving expiry provenance.",
            }
        ],
        "add_edges": [
            {
                "source": "fulfilment_stage_3",
                "target": "carrier_quote_cache",
                "label": "looks up fresh carrier quote",
                "technology": "Cache read",
                "sync": "sync",
                "flow": "runtime",
                "description": "Checks for a fresh quote before calling a carrier.",
            },
            {
                "source": "carrier_quote_cache",
                "target": "fulfilment_stage_4",
                "label": "returns quote with expiry provenance",
                "technology": "Typed quote record",
                "sync": "sync",
                "flow": "runtime",
                "description": "Returns only quotes whose bounded freshness policy still holds.",
            },
        ],
        "groups": groups,
    }

    result = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        safety_max_nodes=12,
        resolved_complexity="production",
    )

    assert existing == before
    assert len(result["nodes"]) == 10
    assert len(result["edges"]) == len(before["edges"]) + 2
    assert next(
        node for node in result["nodes"] if node["id"] == "fulfilment_stage_7"
    ) == next(node for node in before["nodes"] if node["id"] == "fulfilment_stage_7")
    assert next(
        edge
        for edge in result["edges"]
        if edge["source"] == "fulfilment_stage_7"
        and edge["target"] == "fulfilment_stage_8"
    ) == next(
        edge
        for edge in before["edges"]
        if edge["source"] == "fulfilment_stage_7"
        and edge["target"] == "fulfilment_stage_8"
    )
    assert "carrier_quote_cache" in result["groups"][1]["nodeIds"]
    cache = next(
        node for node in result["nodes"] if node["id"] == "carrier_quote_cache"
    )
    assert cache["tier"] is None
    assert cache["lane"] == "main"


def test_patch_updates_nodes_and_edges_and_removes_only_selected_edge():
    existing = _domain_graph(5)
    removed_edge = existing["edges"][-1]
    patch = {
        "update_nodes": [
            {
                "id": "fulfilment_stage_2",
                "set": {
                    "label": "Customs Evidence Check",
                    "description": "Validates customs evidence before a cross-border handoff.",
                },
            }
        ],
        "update_edges": [
            {
                "edge_id": "edge_2",
                "set": {
                    "label": "passes customs-ready parcel state",
                    "technology": "Signed customs envelope",
                },
            }
        ],
        "remove_edges": ["edge_5"],
    }

    result = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    updated_node = next(
        node for node in result["nodes"] if node["id"] == "fulfilment_stage_2"
    )
    assert updated_node["label"] == "Customs Evidence Check"
    assert any(
        edge["label"] == "passes customs-ready parcel state"
        and edge["technology"] == "Signed customs envelope"
        for edge in result["edges"]
    )
    assert not any(
        edge["source"] == removed_edge["source"]
        and edge["target"] == removed_edge["target"]
        and edge["label"] == removed_edge["label"]
        for edge in result["edges"]
    )


def test_patch_edge_id_selects_one_of_two_parallel_edges():
    existing = _domain_graph(5)
    first = existing["edges"][0]
    existing["edges"].append(
        {
            **copy.deepcopy(first),
            "label": "distinct route over the same node pair",
        }
    )

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {"remove_edges": ["edge_6"]},
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(result["edges"]) == len(existing["edges"]) - 1
    assert first in result["edges"]
    assert not any(
        edge["label"] == "distinct route over the same node pair"
        for edge in result["edges"]
    )
    assert all(
        str(edge.get("edge_id") or "").startswith("applied:")
        for edge in result["edges"]
    )


def test_patch_rejects_unknown_edge_id():
    existing = _domain_graph(5)

    with pytest.raises(ValueError, match="cannot remove unknown edge"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {"remove_edges": ["edge_99"]},
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_patch_ignores_top_level_null_optional_fields():
    existing = _domain_graph(5)

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_2",
                    "set": {"label": "Customs Evidence Check"},
                }
            ],
            "add_edges": None,
            "title": None,
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert result["title"] == existing["title"]
    assert (
        next(node for node in result["nodes"] if node["id"] == "fulfilment_stage_2")[
            "label"
        ]
        == "Customs Evidence Check"
    )


@pytest.mark.parametrize(
    ("patch", "error"),
    [
        (
            {"update_nodes": [{"id": "invented_stage", "set": {"label": "Invented"}}]},
            "unknown node",
        ),
        (
            {
                "add_edges": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "invented_stage",
                        "label": "sends invented payload",
                        "technology": "Typed event",
                        "sync": "async",
                        "flow": "runtime",
                        "description": "Must not survive deterministic reference validation.",
                    }
                ]
            },
            "references unknown node",
        ),
        ({"remove_nodes": ["fulfilment_stage_2"]}, "references unknown node"),
        ({"replacement_graph": {"nodes": []}}, "unknown graph patch fields"),
    ],
)
def test_invalid_patch_operations_are_rejected_without_mutation(patch, error):
    existing = _domain_graph(5)
    before = copy.deepcopy(existing)

    with pytest.raises(ValueError, match=error):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )

    assert existing == before


def test_patch_has_no_percentage_retention_heuristic():
    existing = _domain_graph(5)
    incident_edge_ids = [
        graph_worker._patch_edge_id(index)
        for index, edge in enumerate(existing["edges"])
        if edge["source"]
        in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
        or edge["target"]
        in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
    ]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "remove_nodes": [
                "fulfilment_stage_2",
                "fulfilment_stage_3",
                "fulfilment_stage_4",
            ],
            "remove_edges": incident_edge_ids,
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert [node["id"] for node in result["nodes"]] == [
        "fulfilment_stage_0",
        "fulfilment_stage_1",
    ]


def _whole_graph_repair_contract(existing):
    return _local_repair_contract(
        failed_layers={
            "components": {
                "node_ids": [node["id"] for node in existing["nodes"]],
                "context_node_ids": [node["id"] for node in existing["nodes"]],
                "addition_count": 2,
            },
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                    for edge in existing["edges"]
                ],
                "context_node_ids": [node["id"] for node in existing["nodes"]],
                "addition_count": 2,
            },
            "composition": {"composition_fields": ["title"]},
        }
    )


@pytest.mark.parametrize("with_contract", [False, True])
def test_incremental_patch_cannot_replace_the_existing_graph(with_contract):
    existing = _domain_graph(5)
    contract = _whole_graph_repair_contract(existing) if with_contract else None

    with pytest.raises(
        ValueError,
        match="incremental patch cannot add and remove nodes together",
    ):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "remove_nodes": [node["id"] for node in existing["nodes"]],
                "remove_edges": [
                    graph_worker._patch_edge_id(index)
                    for index, _edge in enumerate(existing["edges"])
                ],
                "add_nodes": [
                    {
                        "id": "replacement_input",
                        "label": "Unrelated Input",
                        "type": "client",
                        "technology": "Replacement",
                        "description": "Starts an unrelated topology.",
                    },
                    {
                        "id": "replacement_output",
                        "label": "Unrelated Output",
                        "type": "service",
                        "technology": "Replacement",
                        "description": "Ends an unrelated topology.",
                    },
                ],
                "add_edges": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "replacement_input",
                        "label": "replaces the approved graph",
                        "technology": "Replacement",
                        "sync": "sync",
                        "flow": "runtime",
                        "description": "Must not replace the approved topology.",
                    },
                    {
                        "source": "fulfilment_stage_0",
                        "target": "replacement_output",
                        "label": "replaces the approved graph output",
                        "technology": "Replacement",
                        "sync": "sync",
                        "flow": "runtime",
                        "description": "Must not replace the approved topology.",
                    },
                ],
            },
            safety_max_nodes=20,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_unscoped_incremental_patch_cannot_rewrite_every_existing_record():
    existing = _domain_graph(5)
    patch = {
        "title": "Unrelated replacement",
        "update_nodes": [
            {
                "id": node["id"],
                "set": {
                    "label": f"Replacement {index}",
                    "description": "Owns unrelated replacement behavior.",
                },
            }
            for index, node in enumerate(existing["nodes"])
        ],
        "update_edges": [
            {
                "edge_id": graph_worker._patch_edge_id(index),
                "set": {
                    "source": existing["nodes"][-1]["id"],
                    "target": existing["nodes"][0]["id"],
                    "label": f"replacement route {index}",
                },
            }
            for index, _edge in enumerate(existing["edges"])
        ],
    }

    with pytest.raises(
        ValueError,
        match="incremental patch cannot rewrite every existing node",
    ):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=20,
            resolved_complexity="prototype",
        )


def test_exact_contract_can_update_every_cited_node_in_small_graph():
    existing = _domain_graph(2)
    node_ids = [node["id"] for node in existing["nodes"]]
    contract = _local_repair_contract(
        failed_layers={"components": {"node_ids": node_ids}}
    )

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_nodes": [
                {
                    "id": node_id,
                    "set": {
                        "description": f"Owns the corrected responsibility for {node_id}."
                    },
                }
                for node_id in node_ids
            ]
        },
        safety_max_nodes=20,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert [node["id"] for node in updated["nodes"]] == node_ids
    assert all(
        node["description"].startswith("Owns the corrected responsibility")
        for node in updated["nodes"]
    )


def test_repair_contract_rejects_out_of_scope_node_mutation_before_normalization():
    existing = _domain_graph(5)
    before = copy.deepcopy(existing)
    contract = _local_repair_contract(
        failed_layers={"components": {"node_ids": ["fulfilment_stage_0"]}}
    )

    with pytest.raises(ValueError, match="changed locked node"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "update_nodes": [
                    {
                        "id": "fulfilment_stage_1",
                        "set": {"description": "Out-of-scope mutation."},
                    }
                ],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )

    assert existing == before


def test_disconnected_exact_record_patch_preserves_uncited_records():
    existing = _domain_graph(4)
    before = copy.deepcopy(existing)
    selected_edge = {
        key: existing["edges"][0][key] for key in ("source", "target", "label")
    }
    context_node_ids = [
        "fulfilment_stage_1",
        "fulfilment_stage_2",
        "fulfilment_stage_3",
    ]
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "addition_count": 1,
                "context_node_ids": context_node_ids,
            },
            "connections": {
                "edge_selectors": [selected_edge],
                "addition_count": 2,
                "context_node_ids": context_node_ids,
                "connection_addition_obligations": [
                    {
                        "source": "$new_node_1",
                        "target": target,
                        "required_contract": f"repairs {target}",
                    }
                    for target in (
                        "fulfilment_stage_2",
                        "fulfilment_stage_3",
                    )
                ],
            },
        }
    )
    patch = {
        "update_edges": [
            {
                "edge_id": "edge_1",
                "set": {"description": "Carries the corrected intake handoff."},
            }
        ],
        "add_nodes": [
            {
                "id": "repair_worker",
                "label": "Repair Worker",
                "type": "service",
                "technology": "Bounded worker",
                "description": "Repairs one parcel state.",
            }
        ],
        "add_edges": [
            {
                "source": "repair_worker",
                "target": target,
                "label": f"repairs {target}",
                "technology": "Versioned event",
                "sync": "async",
                "flow": "control",
                "description": "Carries the bounded repair.",
            }
            for target in ("fulfilment_stage_2", "fulfilment_stage_3")
        ],
    }

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        safety_max_nodes=5,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert existing == before
    assert updated["nodes"][: len(before["nodes"])] == before["nodes"]
    assert updated["edges"][0]["description"] == (
        "Carries the corrected intake handoff."
    )
    assert updated["edges"][1 : len(before["edges"])] == before["edges"][1:]
    assert updated["title"] == before["title"]
    assert updated.get("groups") == before.get("groups")
    assert updated["sequence"] == before["sequence"]


def test_semantic_repair_can_update_an_edge_title_and_indexed_assumption():
    existing = _domain_graph(5)
    before = copy.deepcopy(existing)
    selected_edge = {
        key: existing["edges"][0][key] for key in ("source", "target", "label")
    }
    contract = _local_repair_contract(
        failed_layers={
            "connections": {"edge_selectors": [selected_edge]},
            "composition": {
                "composition_fields": ["title", "assumptions"],
                "assumption_indexes": [0],
            },
        }
    )

    validate_local_repair_admission(contract, graph=existing)
    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {"description": "Carries the corrected intake contract."},
                }
            ],
            "title": "Corrected marketplace fulfilment control loop",
            "assumptions": ["Carriers publish versioned durable parcel events."],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert existing == before
    assert updated["title"] == "Corrected marketplace fulfilment control loop"
    assert updated["assumptions"] == [
        "Carriers publish versioned durable parcel events."
    ]
    assert updated["edges"][0]["description"] == (
        "Carries the corrected intake contract."
    )
    assert updated["edges"][1:] == before["edges"][1:]
    assert updated["nodes"] == before["nodes"]


def test_disconnected_semantic_repair_can_append_one_exact_assumption():
    existing = _domain_graph(6)
    before = copy.deepcopy(existing)
    selected_indexes = (0, len(existing["edges"]) - 1)
    selected_edges = [
        {key: existing["edges"][index][key] for key in ("source", "target", "label")}
        for index in selected_indexes
    ]
    contract = _local_repair_contract(
        failed_layers={
            "connections": {"edge_selectors": selected_edges},
            "composition": {
                "composition_fields": ["assumptions"],
                "composition_append_counts": {"assumptions": 1},
            },
        }
    )
    appended_assumption = "Exception carriers expose durable reconciliation status."

    validate_local_repair_admission(contract, graph=existing)
    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_edges": [
                {
                    "edge_id": graph_worker._patch_edge_id(index),
                    "set": {"description": f"Corrected disconnected contract {index}."},
                }
                for index in selected_indexes
            ],
            "assumptions": [*existing["assumptions"], appended_assumption],
        },
        safety_max_nodes=8,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert existing == before
    assert updated["assumptions"] == [*before["assumptions"], appended_assumption]
    for index, edge in enumerate(updated["edges"]):
        if index in selected_indexes:
            assert edge["description"] == f"Corrected disconnected contract {index}."
        else:
            assert edge == before["edges"][index]


def test_semantic_component_addition_can_update_the_exact_title():
    existing = _domain_graph(4)
    before = copy.deepcopy(existing)
    anchor_node_id = "fulfilment_stage_1"
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": [anchor_node_id],
                "addition_count": 1,
            },
            "connections": {
                "context_node_ids": [anchor_node_id],
                "addition_count": 1,
                "connection_addition_obligations": [
                    {
                        "source": anchor_node_id,
                        "target": "$new_node_1",
                        "required_contract": "delegates exception handling",
                    }
                ],
            },
            "composition": {"composition_fields": ["title"]},
        }
    )

    validate_local_repair_admission(contract, graph=existing)
    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "add_nodes": [
                {
                    "id": "exception_owner",
                    "label": "Exception Owner",
                    "type": "service",
                    "technology": "Bounded worker",
                    "description": "Owns the missing exception responsibility.",
                }
            ],
            "add_edges": [
                {
                    "source": anchor_node_id,
                    "target": "exception_owner",
                    "label": "delegates exception handling",
                    "technology": "Versioned event",
                    "sync": "async",
                    "flow": "control",
                    "description": "Carries one bounded exception handoff.",
                }
            ],
            "title": "Marketplace fulfilment and exception control loop",
        },
        safety_max_nodes=6,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert existing == before
    assert updated["title"] == "Marketplace fulfilment and exception control loop"
    assert updated["nodes"][:-1] == before["nodes"]
    assert updated["nodes"][-1]["id"] == "exception_owner"
    assert updated["edges"][: len(before["edges"])] == before["edges"]
    assert updated["edges"][-1]["target"] == "exception_owner"


@pytest.mark.parametrize("field", ["groups", "sequence", "assumptions"])
def test_semantic_repair_rejects_unsafe_whole_collection_authority(field):
    existing = _domain_graph(8, production=True)
    selected_edge = {
        key: existing["edges"][0][key] for key in ("source", "target", "label")
    }
    contract = _local_repair_contract(
        failed_layers={
            "connections": {"edge_selectors": [selected_edge]},
            "composition": {"composition_fields": [field]},
        }
    )

    with pytest.raises(ValueError, match=f"whole {field} collection"):
        validate_local_repair_admission(contract, graph=existing)


def test_failed_connection_layer_requires_explicit_edge_addition_permission():
    existing = _domain_graph(5)
    contract = _local_repair_contract(failed_layers={"connections": {}})

    with pytest.raises(
        ValueError,
        match="failed connections layer must cite an edge or declare additions",
    ):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "add_edges": [
                    {
                        "source": "fulfilment_stage_3",
                        "target": "fulfilment_stage_1",
                        "label": "returns bounded exception",
                        "technology": "Typed exception event",
                        "sync": "async",
                        "flow": "control",
                        "description": "Returns an exception to its recovery owner.",
                    }
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_repair_contract_rejects_invalid_addition_count_without_type_error():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={"connections": {"addition_count": 1}}
    )
    contract["layers"]["connections"]["addition_count"] = "one"

    with pytest.raises(
        ValueError, match="addition_count must be a non-negative integer"
    ):
        graph_worker.validate_repair_contract(contract, graph=existing)


def test_grouped_component_addition_requires_a_satisfiable_group_target():
    existing = _domain_graph(9, production=True)
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "addition_count": 1,
                "context_node_ids": ["fulfilment_stage_7"],
            },
            "connections": {
                "addition_count": 1,
                "context_node_ids": ["fulfilment_stage_7"],
            },
            "composition": {"composition_fields": ["groups"]},
        }
    )

    with pytest.raises(
        ValueError,
        match="editable existing group or a declared group append",
    ):
        graph_worker.validate_repair_contract(contract, graph=existing)


def test_mixed_render_repair_keeps_passing_graph_layers_locked():
    existing = _domain_graph(5)
    before = copy.deepcopy(existing)
    contract = _local_repair_contract(
        failed_layers={
            "components": {"node_ids": ["fulfilment_stage_0"]},
            "render": {},
        }
    )

    with pytest.raises(ValueError, match="locked connections layer"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "update_edges": [
                    {
                        "edge_id": "edge_1",
                        "set": {"label": "unapproved visual shortcut"},
                    }
                ],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )

    assert existing == before


def test_component_repair_preserves_persisted_render_view_state():
    existing = _domain_graph(5)
    existing["view_state"] = {
        "layoutVersion": 1,
        "nodePositions": {
            "fulfilment_stage_0": {"x": 120.0, "y": 80.0},
        },
        "viewport": {"x": 10.0, "y": 20.0, "k": 0.8},
    }
    contract = _local_repair_contract(
        failed_layers={"components": {"node_ids": ["fulfilment_stage_0"]}}
    )

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_0",
                    "set": {"description": "Owns the corrected intake responsibility."},
                }
            ]
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert updated["view_state"] == existing["view_state"]


def test_group_only_repair_rederives_lane_without_unlocking_components():
    existing = _domain_graph(9, production=True)
    groups = copy.deepcopy(existing["groups"])
    groups[0]["nodeIds"].remove("fulfilment_stage_0")
    groups[2]["nodeIds"].append("fulfilment_stage_0")
    contract = _local_repair_contract(
        failed_layers={
            "composition": {
                "composition_fields": ["groups"],
                "group_ids": ["intake", "outcomes"],
            },
        }
    )

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        {"groups": groups},
        safety_max_nodes=12,
        resolved_complexity="production",
        repair_contract=contract,
    )

    before = next(
        node for node in existing["nodes"] if node["id"] == "fulfilment_stage_0"
    )
    after = next(
        node for node in updated["nodes"] if node["id"] == "fulfilment_stage_0"
    )
    assert before["lane"] == "main"
    assert after["lane"] == "bottom"
    assert after["tier"] is None
    assert {
        field: after[field] for field in graph_worker._PATCH_NODE_MUTABLE_FIELDS
    } == {field: before[field] for field in graph_worker._PATCH_NODE_MUTABLE_FIELDS}


def _two_group_fixture() -> dict:
    return {
        "groups": [
            {"id": "group_1", "nodeIds": ["node_a"]},
            {"id": "group_2", "nodeIds": ["node_b"]},
        ]
    }


def test_group_move_requires_both_source_and_destination_permissions():
    existing = _two_group_fixture()
    replacement = copy.deepcopy(existing["groups"])
    replacement[0]["nodeIds"].remove("node_a")
    replacement[1]["nodeIds"].append("node_a")

    with pytest.raises(ValueError, match="locked group: group_2") as raised:
        graph_worker._validate_group_replacement_scope(
            existing,
            replacement,
            {"group_1"},
        )

    assert graph_worker._patch_validation_coordinates(raised.value) == (
        "groups.group_1.group_2",
        "locked_record_changed",
    )
    with pytest.raises(ValueError, match="locked group: group_1"):
        graph_worker._validate_group_replacement_scope(
            existing,
            replacement,
            {"group_2"},
        )

    graph_worker._validate_group_replacement_scope(
        existing,
        replacement,
        {"group_1", "group_2"},
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "added edges do not match the exact connection addition obligations",
            ("patch.add_edges", "addition_obligation_mismatch"),
        ),
        (
            "added edge labels do not match the exact connection addition obligations",
            ("patch.add_edges", "addition_obligation_mismatch"),
        ),
        (
            "graph patch changed locked edge fields: source",
            ("patch.update_edges", "unauthorized_field_change"),
        ),
    ],
)
def test_patch_validation_coordinates_cover_exact_edge_contract_failures(
    message,
    expected,
):
    assert graph_worker._patch_validation_coordinates(ValueError(message)) == expected


@pytest.mark.asyncio
async def test_contract_corrected_patch_prompt_cannot_repeat_the_invalid_prompt(
    monkeypatch,
):
    existing = _domain_graph(4)
    contract = _local_repair_contract(
        failed_layers={"components": {"node_ids": ["fulfilment_stage_0"]}}
    )
    prompts = []

    async def invalid_patch(**kwargs):
        prompts.append(kwargs["messages"])
        return "{}"

    monkeypatch.setattr(graph_worker, "stream_llm", invalid_patch)
    base_state = {
        "send": None,
        "user_message": "Repair the intake responsibility",
        "graph_revision_count": 1,
        "graph_review": {
            "approved": False,
            "repair_contract": contract,
            "topology_proofs": [],
        },
        "complexity": "prototype",
        "user_id": "user-1",
        "session_id": "thread-1",
    }
    for correction in (
        None,
        {"path": "groups.group_2", "rule": "locked_record_changed"},
    ):
        state = copy.deepcopy(base_state)
        if correction is not None:
            state["graph_review"]["contract_correction"] = correction
        with pytest.raises(graph_worker.GraphPatchRejected):
            await graph_worker._generate_applied_architecture_patch(
                state,
                "Repair the intake responsibility",
                SimpleNamespace(resolved="prototype"),
                existing,
            )

    assert prompts[0] != prompts[1]
    corrected_prompt = prompts[1][0]["content"]
    assert "groups.group_2" in corrected_prompt
    assert "locked_record_changed" in corrected_prompt


@pytest.mark.parametrize(
    ("field", "selectors", "replacement"),
    [
        (
            "sequence",
            {"sequence_indexes": [0]},
            [
                {"step": 1, "nodes": ["fulfilment_stage_0"], "description": "Allowed."},
                {
                    "step": 2,
                    "nodes": ["fulfilment_stage_1"],
                    "description": "Locked edit.",
                },
                {
                    "step": 3,
                    "nodes": ["fulfilment_stage_2"],
                    "description": "Runs observable marketplace step 3.",
                },
                {
                    "step": 4,
                    "nodes": ["fulfilment_stage_3"],
                    "description": "Runs observable marketplace step 4.",
                },
            ],
        ),
        (
            "assumptions",
            {"assumption_indexes": []},
            ["Changed locked assumption."],
        ),
    ],
)
def test_repair_contract_locks_uncited_composition_records(
    field,
    selectors,
    replacement,
):
    existing = _domain_graph(9, production=True)
    contract = _local_repair_contract(
        failed_layers={
            "composition": {
                "composition_fields": [field],
                **selectors,
            },
        }
    )

    with pytest.raises(ValueError, match=f"locked {field} record"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {field: replacement},
            safety_max_nodes=12,
            resolved_complexity="production",
            repair_contract=contract,
        )


def test_over_resource_safety_edges_are_rejected_before_position_can_hide_isolation(
    monkeypatch,
):
    existing = _domain_graph(9, production=True)
    payload = copy.deepcopy(existing)
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if "fulfilment_stage_8" not in {edge["source"], edge["target"]}
    ]
    while len(payload["edges"]) < 20:
        index = len(payload["edges"])
        payload["edges"].append(
            {
                "source": f"fulfilment_stage_{index % 7}",
                "target": f"fulfilment_stage_{(index + 2) % 8}",
                "label": f"carries auxiliary recovery signal {index}",
                "technology": "Typed recovery event",
                "sync": "async",
                "flow": "control",
                "description": "Carries a bounded recovery signal without changing the main path.",
            }
        )
    payload["edges"].append(
        {
            "source": "fulfilment_stage_7",
            "target": "fulfilment_stage_8",
            "label": "connects the final recovery owner",
            "technology": "Typed recovery event",
            "sync": "async",
            "flow": "control",
            "description": "Keeps the final owner connected even when listed last.",
        }
    )

    monkeypatch.setattr(graph_worker.settings, "graph_safety_max_edges", 20)
    with pytest.raises(ValueError, match="20-edge resource-safety ceiling; got 21"):
        graph_worker._normalise_applied_graph(
            payload,
            safety_max_nodes=9,
            resolved_complexity="production",
        )


def test_at_cap_patch_updates_an_edge_in_place_instead_of_disappearing():
    existing = _domain_graph(9, production=True)
    while len(existing["edges"]) < 20:
        index = len(existing["edges"])
        existing["edges"].append(
            {
                "source": "fulfilment_stage_0",
                "target": "fulfilment_stage_8",
                "label": f"carries bounded exception signal {index}",
                "technology": "Typed exception event",
                "sync": "async",
                "flow": "control",
                "description": "Carries a bounded exception signal to its recovery owner.",
            }
        )
    existing = graph_worker._normalise_applied_graph(
        existing,
        safety_max_nodes=9,
        resolved_complexity="production",
    )
    target = existing["edges"][0]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {"flow": "feedback", "type": "loop"},
                }
            ]
        },
        safety_max_nodes=9,
        resolved_complexity="production",
    )

    assert len(result["edges"]) == 20
    updated = next(
        edge
        for edge in result["edges"]
        if edge["source"] == target["source"] and edge["target"] == target["target"]
    )
    assert updated["flow"] == "feedback"
    assert updated["type"] == "loop"


def test_semantically_empty_patch_is_rejected():
    existing = _domain_graph(5)

    with pytest.raises(ValueError, match="produced no semantic change"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "update_nodes": [
                    {
                        "id": "fulfilment_stage_2",
                        "set": {"label": "Fulfilment Stage 2"},
                    }
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_message_queue_is_a_supported_architecture_primitive():
    graph = _domain_graph(5)
    graph["nodes"][2]["type"] = "queue"
    graph["nodes"][2]["technology"] = "Durable event stream"

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["nodes"][2]["type"] == "queue"


@pytest.mark.parametrize(
    "label",
    [
        "promote canary or rollback release",
        "record COMMITTED / NOT_FOUND / STILL_UNKNOWN",
        "auto-route pre-approved low-risk action",
    ],
)
def test_graph_parser_preserves_repairable_control_edges(label):
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = label

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["label"] == label


def test_graph_validator_accepts_complete_automatic_authorization_envelope():
    graph = _domain_graph(5)
    graph["edges"][0].update(
        {
            "label": "auto-route pre-approved bounded action",
            "technology": "Signed payload and target envelope",
            "description": (
                "Binds the policy version, expiry, and idempotency key before durable reservation."
            ),
        }
    )

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["label"] == "auto-route pre-approved bounded action"


def test_graph_parser_preserves_collapsed_outcomes_for_critic_repair():
    graph = _domain_graph(5)
    graph["edges"][0].update(
        {
            "label": "reconcile operation status",
            "technology": "Authoritative read-back",
            "description": "Returns COMMITTED, NOT_FOUND, or STILL_UNKNOWN as one result.",
        }
    )

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["label"] == "reconcile operation status"


def test_graph_parser_preserves_combined_deployment_edge_for_critic_repair():
    graph = _domain_graph(5)
    graph["edges"][0].update(
        {
            "label": "deploy release",
            "technology": "Canary/promoted deployment",
            "description": "Routes either stage into the same runtime transition.",
        }
    )

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["technology"] == "Canary/promoted deployment"


def test_graph_parser_keeps_independent_control_defects_for_one_critic_review():
    graph = _domain_graph(5)
    graph["edges"][0].update(
        {
            "label": "deploy release",
            "technology": "Canary/promoted deployment",
            "description": "Routes either stage into the same runtime transition.",
        }
    )
    graph["edges"][1].update(
        {
            "label": "reconcile operation status",
            "technology": "Authoritative read-back",
            "description": "Returns COMMITTED, NOT_FOUND, or STILL_UNKNOWN as one result.",
        }
    )

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(normalised["edges"]) == len(graph["edges"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Update Fulfilment Stage 1 description",
        "Improve Fulfilment Stage 1 description",
    ],
)
async def test_existing_applied_graph_local_edits_use_incremental_patch_lane(
    monkeypatch,
    message,
):
    existing = _domain_graph(5)
    target_id = existing["nodes"][1]["id"]
    topology_calls = []
    patch_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        raise AssertionError("local graph edits must not redraw the full topology")

    async def fake_stream_llm(**kwargs):
        patch_calls.append(kwargs)
        return json.dumps(
            {
                "update_nodes": [
                    {
                        "id": target_id,
                        "set": {
                            "description": "Owns the corrected cache responsibility."
                        },
                    }
                ]
            }
        )

    async def send(_event):
        return None

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)

    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": False,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": message,
            "user_message": message,
            "history": [],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert topology_calls == []
    assert len(patch_calls) == 1
    assert patch_calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert message in patch_calls[0]["messages"][0]["content"]
    assert (
        next(node for node in result["graph_data"]["nodes"] if node["id"] == target_id)[
            "description"
        ]
        == "Owns the corrected cache responsibility."
    )


@pytest.mark.asyncio
async def test_first_turn_addition_can_extend_without_unlocking_existing_records(
    monkeypatch,
):
    existing = _domain_graph(5)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "add_nodes": [
                    {
                        "id": "prometheus",
                        "label": "Prometheus",
                        "type": "service",
                        "technology": "Prometheus",
                        "description": "Collects fulfilment service metrics.",
                    }
                ],
                "add_edges": [
                    {
                        "source": "fulfilment_stage_1",
                        "target": "prometheus",
                        "label": "exports service metrics",
                        "technology": "Prometheus scrape protocol",
                        "sync": "async",
                        "flow": "control",
                        "description": "Exports bounded operational measurements.",
                    }
                ],
            }
        )

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": "Add Prometheus connected to Fulfilment Stage 1",
            "graph_review": {},
            "complexity": "prototype",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Add Prometheus connected to Fulfilment Stage 1",
        SimpleNamespace(resolved="prototype"),
        existing,
    )

    assert len(calls) == 1
    assert result["nodes"][: len(existing["nodes"])] == existing["nodes"]
    assert result["edges"][: len(existing["edges"])] == existing["edges"]
    assert result["nodes"][-1]["id"] == "prometheus"


async def _run_first_turn_patch(monkeypatch, existing, message, patch):
    async def fake_stream_llm(**_kwargs):
        return json.dumps(patch)

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    return await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": message,
            "graph_review": {},
            "complexity": "prototype",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        message,
        SimpleNamespace(resolved="prototype"),
        existing,
    )


def _cache_to_store_edge(
    *,
    source="fulfilment_stage_1",
    target="fulfilment_stage_3",
):
    return {
        "source": source,
        "target": target,
        "label": "writes cached fulfilment state",
        "technology": "Typed cache record",
        "sync": "sync",
        "flow": "runtime",
        "description": "Writes the bounded cache record to the named store.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_1",
                    "set": {"description": "An edge request cannot rewrite a node."},
                }
            ],
            "add_edges": [_cache_to_store_edge()],
        },
        {
            "add_edges": [
                _cache_to_store_edge(target="fulfilment_stage_4"),
            ]
        },
    ],
)
async def test_first_turn_connection_rejects_node_mutation_and_wrong_endpoint(
    monkeypatch,
    patch,
):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"
    existing["nodes"][3]["label"] = "Store"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Connect Cache to Store",
            patch,
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_connection_accepts_exact_named_endpoints(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"
    existing["nodes"][3]["label"] = "Store"

    result = await _run_first_turn_patch(
        monkeypatch,
        existing,
        "Connect Cache to Store",
        {"add_edges": [_cache_to_store_edge()]},
    )

    assert result["edges"][-1]["source"] == "fulfilment_stage_1"
    assert result["edges"][-1]["target"] == "fulfilment_stage_3"


@pytest.mark.asyncio
async def test_first_turn_connection_deletion_cannot_remove_named_node(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Delete the Cache connection",
            {
                "remove_nodes": ["fulfilment_stage_1"],
                "remove_edges": ["edge_1", "edge_2"],
            },
        )

    assert raised.value.code == "graph_edit_scope_ambiguous"


@pytest.mark.asyncio
async def test_remove_typo_from_label_cannot_delete_the_node(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cahce"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Remove the typo from the Cahce label",
            {"remove_nodes": ["fulfilment_stage_1"]},
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_rename_with_new_label_cannot_change_technology(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Rename Cache with the label Redis",
            {
                "update_nodes": [
                    {
                        "id": "fulfilment_stage_1",
                        "set": {
                            "label": "Redis",
                            "technology": "Redis Enterprise",
                        },
                    }
                ]
            },
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_named_addition_rejects_extra_nodes_and_subgraph(monkeypatch):
    existing = _domain_graph(5)

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Add Prometheus connected to Fulfilment Stage 1",
            {
                "add_nodes": [
                    {
                        "id": "prometheus",
                        "label": "Prometheus",
                        "type": "service",
                        "technology": "Prometheus",
                        "description": "Collects fulfilment service metrics.",
                    },
                    {
                        "id": "unrequested_worker",
                        "label": "Unrequested Worker",
                        "type": "service",
                        "technology": "Unrequested runtime",
                        "description": "Adds an unrelated topology branch.",
                    },
                ],
                "add_edges": [
                    {
                        "source": "fulfilment_stage_1",
                        "target": "prometheus",
                        "label": "exports service metrics",
                        "technology": "Prometheus scrape protocol",
                        "sync": "async",
                        "flow": "control",
                        "description": "Exports bounded operational measurements.",
                    },
                    {
                        "source": "prometheus",
                        "target": "unrequested_worker",
                        "label": "starts unrelated work",
                        "technology": "Unrequested protocol",
                        "sync": "async",
                        "flow": "runtime",
                        "description": "Extends the graph beyond the requested component.",
                    },
                ],
            },
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_named_addition_rejects_uncited_connection(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Add Prometheus connected to Cache",
            {
                "add_nodes": [
                    {
                        "id": "prometheus",
                        "label": "Prometheus",
                        "type": "service",
                        "technology": "Prometheus",
                        "description": "Collects fulfilment service metrics.",
                    }
                ],
                "add_edges": [
                    _cache_to_store_edge(
                        source="prometheus",
                        target="fulfilment_stage_4",
                    )
                ],
            },
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_named_addition_accepts_existing_connection_anchor(
    monkeypatch,
):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    result = await _run_first_turn_patch(
        monkeypatch,
        existing,
        "Add Prometheus connected to Cache",
        {
            "add_nodes": [
                {
                    "id": "prometheus",
                    "label": "Prometheus",
                    "type": "service",
                    "technology": "Prometheus",
                    "description": "Collects fulfilment service metrics.",
                }
            ],
            "add_edges": [
                {
                    "source": "fulfilment_stage_1",
                    "target": "prometheus",
                    "label": "exports service metrics",
                    "technology": "Prometheus scrape protocol",
                    "sync": "async",
                    "flow": "control",
                    "description": "Exports bounded operational measurements.",
                }
            ],
        },
    )

    assert result["nodes"][-1]["id"] == "prometheus"
    assert result["edges"][-1]["source"] == "fulfilment_stage_1"


def test_critic_repair_rejects_more_additions_than_scored():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 1,
            },
            "connections": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 2,
            },
        }
    )
    patch = {
        "add_nodes": [
            {
                "id": node_id,
                "label": node_id.replace("_", " ").title(),
                "type": "service",
                "technology": "Bounded service",
                "description": "Adds a repair-owned responsibility.",
            }
            for node_id in ("requested_owner", "unrelated_owner")
        ],
        "add_edges": [
            _cache_to_store_edge(target="requested_owner"),
            _cache_to_store_edge(
                source="requested_owner",
                target="unrelated_owner",
            ),
        ],
    }

    with pytest.raises(ValueError, match="wrong number of nodes"):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=10,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_repair_requires_an_added_edge_for_every_added_node():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 2,
            },
            "connections": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 2,
            },
        }
    )
    patch = {
        "add_nodes": [
            {
                "id": node_id,
                "label": node_id.replace("_", " ").title(),
                "type": "service",
                "technology": "Bounded service",
                "description": "Adds a repair-owned responsibility.",
            }
            for node_id in ("attached_owner", "unattached_owner")
        ],
        "add_edges": [
            _cache_to_store_edge(target="attached_owner"),
            _cache_to_store_edge(source="attached_owner", target="fulfilment_stage_1"),
        ],
    }

    with pytest.raises(ValueError, match="every added node must have"):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=10,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_grouped_repair_requires_group_placement_for_every_added_node():
    existing = _domain_graph(5)
    existing["groups"] = [
        {
            "id": "runtime",
            "label": "Runtime",
            "kind": "runtime",
            "nodeIds": [node["id"] for node in existing["nodes"]],
        }
    ]
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 2,
            },
            "connections": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 2,
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_1",
                        "target": "$new_node_1",
                        "required_contract": "writes cached fulfilment state",
                    },
                    {
                        "source": "fulfilment_stage_1",
                        "target": "$new_node_2",
                        "required_contract": "writes cached fulfilment state",
                    },
                ],
            },
            "composition": {
                "group_ids": ["runtime"],
                "composition_fields": ["groups"],
            },
        }
    )
    new_node_ids = ("grouped_owner", "ungrouped_owner")
    patch = {
        "add_nodes": [
            {
                "id": node_id,
                "label": node_id.replace("_", " ").title(),
                "type": "service",
                "technology": "Bounded service",
                "description": "Adds a repair-owned responsibility.",
            }
            for node_id in new_node_ids
        ],
        "add_edges": [_cache_to_store_edge(target=node_id) for node_id in new_node_ids],
        "groups": [
            {
                **existing["groups"][0],
                "nodeIds": [
                    *existing["groups"][0]["nodeIds"],
                    "grouped_owner",
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="every added node must be placed"):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=10,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def _grouped_component_addition_repair() -> tuple[dict, dict, dict]:
    existing = _domain_graph(5)
    existing["groups"] = [
        {
            "id": "runtime",
            "label": "Runtime",
            "kind": "runtime",
            "nodeIds": [node["id"] for node in existing["nodes"][:3]],
        },
        {
            "id": "operations",
            "label": "Operations",
            "kind": "operations",
            "nodeIds": [node["id"] for node in existing["nodes"][3:]],
        },
    ]
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "addition_count": 1,
                "context_node_ids": ["fulfilment_stage_1"],
            },
            "connections": {
                "addition_count": 1,
                "context_node_ids": ["fulfilment_stage_1"],
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_1",
                        "target": "$new_node_1",
                        "required_contract": "routes runtime telemetry",
                    }
                ],
            },
            "composition": {
                "composition_fields": ["groups"],
                "group_ids": ["runtime"],
            },
        }
    )
    patch = {
        "add_nodes": [
            {
                "id": "runtime_telemetry",
                "label": "Runtime Telemetry",
                "type": "service",
                "technology": "Metrics collector",
                "description": "Collects bounded runtime telemetry.",
            }
        ],
        "add_edges": [
            {
                "source": "fulfilment_stage_1",
                "target": "runtime_telemetry",
                "label": "routes runtime telemetry",
                "technology": "Typed telemetry event",
                "sync": "async",
                "flow": "runtime",
                "description": "Routes telemetry to its bounded owner.",
            }
        ],
        "groups": [
            {
                **existing["groups"][0],
                "nodeIds": [
                    *existing["groups"][0]["nodeIds"],
                    "runtime_telemetry",
                ],
            },
            copy.deepcopy(existing["groups"][1]),
        ],
    }
    return existing, contract, patch


def test_grouped_component_addition_changes_only_the_selected_existing_group():
    existing, contract, patch = _grouped_component_addition_repair()

    updated = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert updated["groups"][0]["nodeIds"][-1] == "runtime_telemetry"
    assert updated["groups"][1] == existing["groups"][1]


def test_grouped_component_addition_rejects_an_uncited_group_change():
    existing, contract, patch = _grouped_component_addition_repair()
    patch["groups"][1]["label"] = "Changed operations"

    with pytest.raises(ValueError, match="changed locked group: operations"):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_grouped_component_addition_rejects_membership_in_multiple_groups():
    existing, contract, patch = _grouped_component_addition_repair()
    contract["layers"]["composition"]["group_ids"].append("operations")
    patch["groups"][1]["nodeIds"].append("runtime_telemetry")

    with pytest.raises(ValueError, match="placed in exactly one group"):
        graph_worker._apply_applied_graph_patch(
            existing,
            patch,
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_connection_addition_rejects_unrelated_endpoints():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "context_node_ids": [
                    "fulfilment_stage_1",
                    "fulfilment_stage_2",
                ],
                "addition_count": 1,
            }
        }
    )

    with pytest.raises(ValueError, match="named connection scope"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "add_edges": [
                    _cache_to_store_edge(
                        source="fulfilment_stage_3",
                        target="fulfilment_stage_4",
                    )
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


@pytest.mark.parametrize(
    "added_edges",
    [
        [
            _cache_to_store_edge(
                source="fulfilment_stage_2",
                target="fulfilment_stage_1",
            )
        ],
        [
            _cache_to_store_edge(
                source="fulfilment_stage_1",
                target="fulfilment_stage_3",
            ),
            _cache_to_store_edge(
                source="fulfilment_stage_2",
                target="fulfilment_stage_4",
            ),
        ],
    ],
)
def test_critic_connection_additions_require_exact_directed_pairs(added_edges):
    existing = _domain_graph(5)
    obligations = [
        {
            "source": "fulfilment_stage_1",
            "target": "fulfilment_stage_2",
            "required_contract": "Apply the first exact route.",
        }
    ]
    context_node_ids = ["fulfilment_stage_1", "fulfilment_stage_2"]
    if len(added_edges) == 2:
        obligations.append(
            {
                "source": "fulfilment_stage_3",
                "target": "fulfilment_stage_4",
                "required_contract": "Apply the second exact route.",
            }
        )
        context_node_ids.extend(["fulfilment_stage_3", "fulfilment_stage_4"])
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "context_node_ids": context_node_ids,
                "addition_count": len(obligations),
                "connection_addition_obligations": obligations,
            }
        }
    )

    with pytest.raises(ValueError, match="exact connection addition obligations"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {"add_edges": added_edges},
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_component_addition_allows_only_authorized_existing_edge_additions():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": ["fulfilment_stage_0"],
                "addition_count": 1,
            },
            "connections": {
                "context_node_ids": [
                    "fulfilment_stage_0",
                    "fulfilment_stage_1",
                    "fulfilment_stage_3",
                ],
                "addition_count": 2,
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_0",
                        "target": "$new_node_1",
                        "required_contract": "writes cached fulfilment state",
                    },
                    {
                        "source": "fulfilment_stage_1",
                        "target": "fulfilment_stage_3",
                        "required_contract": "writes cached fulfilment state",
                    },
                ],
            },
        }
    )
    patch = {
        "add_nodes": [
            {
                "id": "cache_owner",
                "label": "Cache Owner",
                "type": "service",
                "technology": "Bounded cache service",
                "description": "Owns cached fulfilment state.",
            }
        ],
        "add_edges": [
            _cache_to_store_edge(
                source="fulfilment_stage_0",
                target="cache_owner",
            ),
            _cache_to_store_edge(
                source="fulfilment_stage_1",
                target="fulfilment_stage_3",
            ),
        ],
    }

    validate_local_repair_admission(contract, graph=existing)
    updated = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        safety_max_nodes=7,
        resolved_complexity="prototype",
        repair_contract=contract,
    )

    assert updated["nodes"][-1]["id"] == "cache_owner"
    assert updated["edges"][-1]["source"] == "fulfilment_stage_1"

    uncited_patch = copy.deepcopy(patch)
    uncited_patch["add_edges"][1].update(
        source="fulfilment_stage_3",
        target="fulfilment_stage_1",
    )
    with pytest.raises(ValueError, match="exact connection addition obligations"):
        graph_worker._apply_applied_graph_patch(
            existing,
            uncited_patch,
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_component_addition_rejects_connection_to_uncited_node():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 1,
            },
            "connections": {
                "context_node_ids": ["fulfilment_stage_1"],
                "addition_count": 1,
            },
        }
    )

    with pytest.raises(ValueError, match="named connection scope"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "add_nodes": [
                    {
                        "id": "requested_owner",
                        "label": "Requested Owner",
                        "type": "service",
                        "technology": "Bounded service",
                        "description": "Adds the repair-owned responsibility.",
                    }
                ],
                "add_edges": [
                    _cache_to_store_edge(
                        source="requested_owner",
                        target="fulfilment_stage_4",
                    )
                ],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


def test_critic_composition_repair_rejects_excess_appends():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "composition": {
                "composition_fields": ["assumptions"],
                "composition_append_counts": {"assumptions": 1},
            }
        }
    )

    with pytest.raises(ValueError, match="wrong number of assumptions"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "assumptions": [
                    *existing["assumptions"],
                    "Redis is managed.",
                    "Payments use an unrelated provider.",
                ]
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


@pytest.mark.parametrize("field", ["groups", "sequence", "assumptions"])
def test_composition_repair_rejects_undeclared_appends(field):
    existing = _domain_graph(8, production=True)
    contract = _local_repair_contract(
        failed_layers={
            "composition": {
                "composition_fields": [field],
                "group_ids": (
                    [existing["groups"][0]["id"]] if field == "groups" else []
                ),
                "sequence_indexes": [0] if field == "sequence" else [],
                "assumption_indexes": [0] if field == "assumptions" else [],
            }
        }
    )
    appended_records = {
        "groups": [
            *existing["groups"],
            {
                "id": "undeclared_zone",
                "label": "Undeclared Zone",
                "kind": "runtime",
                "nodeIds": [],
            },
        ],
        "sequence": [
            *existing["sequence"],
            {
                "step": len(existing["sequence"]) + 1,
                "nodes": [existing["nodes"][-1]["id"]],
                "description": "Undeclared step.",
            },
        ],
        "assumptions": [*existing["assumptions"], "Undeclared assumption."],
    }

    with pytest.raises(
        ValueError,
        match=f"appended the wrong number of {field} records",
    ):
        graph_worker._apply_applied_graph_patch(
            existing,
            {field: appended_records[field]},
            safety_max_nodes=8,
            resolved_complexity="production",
            repair_contract=contract,
        )


def test_connection_addition_rejects_endpoints_outside_named_context():
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "connections": {
                "addition_count": 1,
                "context_node_ids": [
                    existing["nodes"][0]["id"],
                    existing["nodes"][1]["id"],
                ],
            }
        }
    )

    with pytest.raises(ValueError, match="outside the named connection scope"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "add_edges": [
                    {
                        "source": existing["nodes"][1]["id"],
                        "target": existing["nodes"][2]["id"],
                        "label": "bypasses unnamed context",
                        "technology": "Typed event",
                        "sync": "async",
                        "flow": "runtime",
                        "description": "Attempts an uncited connection.",
                    }
                ]
            },
            safety_max_nodes=5,
            resolved_complexity="prototype",
            repair_contract=contract,
        )


@pytest.mark.asyncio
async def test_first_turn_assumption_addition_accepts_one_requested_record(monkeypatch):
    existing = _domain_graph(5)
    requested = "Redis is managed."

    result = await _run_first_turn_patch(
        monkeypatch,
        existing,
        "Add the assumption: Redis is managed.",
        {"assumptions": [*existing["assumptions"], requested]},
    )

    assert result["assumptions"] == [*existing["assumptions"], requested]


@pytest.mark.asyncio
async def test_first_turn_assumption_addition_rejects_multiple_new_records(monkeypatch):
    existing = _domain_graph(5)

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Add the assumption: Redis is managed.",
            {
                "assumptions": [
                    *existing["assumptions"],
                    "Redis is managed.",
                    "An unrelated payment processor is managed.",
                ]
            },
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_1",
                    "set": {"description": "A rename request cannot rewrite scope."},
                }
            ]
        },
        {"remove_nodes": ["fulfilment_stage_1"]},
    ],
)
async def test_first_turn_rename_cannot_change_other_fields_or_delete_target(
    monkeypatch,
    patch,
):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    async def fake_stream_llm(**_kwargs):
        return json.dumps(patch)

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Rename the Cache node",
                "graph_review": {},
                "complexity": "prototype",
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Rename the Cache node",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_rename_rejects_unpermitted_normalization_change(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1].update(
        {
            "label": "Cache",
            "technology": "Book objective",
        }
    )

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Rename the Cache node",
            {
                "update_nodes": [
                    {
                        "id": "fulfilment_stage_1",
                        "set": {"label": "Fulfilment Cache"},
                    }
                ]
            },
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"


@pytest.mark.asyncio
async def test_first_turn_semantic_no_op_has_typed_failure_code(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await _run_first_turn_patch(
            monkeypatch,
            existing,
            "Rename the Cache node",
            {
                "update_nodes": [
                    {
                        "id": "fulfilment_stage_1",
                        "set": {"label": "Cache"},
                    }
                ]
            },
        )

    assert raised.value.code == "graph_patch_no_effect"


@pytest.mark.asyncio
async def test_first_turn_update_without_field_fails_before_patch_model(monkeypatch):
    existing = _domain_graph(5)
    existing["nodes"][1]["label"] = "Cache"
    calls = []

    async def fail_model(**kwargs):
        calls.append(kwargs)
        raise AssertionError("an unspecified field must fail before the provider call")

    monkeypatch.setattr(graph_worker, "stream_llm", fail_model)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Update Cache",
                "graph_review": {},
                "complexity": "prototype",
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Update Cache",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_edit_scope_ambiguous"
    assert calls == []


@pytest.mark.asyncio
async def test_ambiguous_first_turn_edit_fails_before_the_patch_model(monkeypatch):
    existing = _domain_graph(5)

    async def fail_model(**_kwargs):
        raise AssertionError("ambiguous edits must fail before the provider call")

    monkeypatch.setattr(graph_worker, "stream_llm", fail_model)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Improve observability",
                "graph_review": {},
                "complexity": "prototype",
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Improve observability",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_edit_scope_ambiguous"


@pytest.mark.asyncio
async def test_new_applied_topic_replaces_instead_of_patching_existing_graph(
    monkeypatch,
):
    existing = _domain_graph(5)
    topology_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        return SimpleNamespace(text="not-json", finish_reason="end_turn")

    async def fail_patch(**_kwargs):
        raise AssertionError("a new system request must not patch the prior domain")

    async def send(_event):
        return None

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
    monkeypatch.setattr(graph_worker, "stream_llm", fail_patch)

    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": True,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": "Design a fraud detection system",
            "user_message": "Design a fraud detection system",
            "history": [],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert len(topology_calls) == 1
    assert result["graph_data"] == existing


@pytest.mark.asyncio
async def test_ambiguous_graph_edit_with_followup_markup_preserves_approved_graph(
    monkeypatch,
):
    existing = _domain_graph(5)
    called_modes = []

    async def fake_generate_applied_architecture(state, _query, _profile):
        called_modes.append(state.get("graph_intent"))
        if state.get("graph_intent") == "edit":
            raise graph_worker.GraphPatchRejected(
                "graph_edit_scope_ambiguous",
                "edit scope is ambiguous",
            )
        raise AssertionError("an ambiguous edit must not start a full graph rebuild")

    async def send(_event):
        return None

    monkeypatch.setattr(
        graph_worker,
        "_generate_applied_architecture",
        fake_generate_applied_architecture,
    )

    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": True,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": "Expand the monitoring component while preserving the original graph topic and existing components. Add exactly one directly connected responsibility.",
            "user_message": "Expand the monitoring component while preserving the original graph topic and existing components. Add exactly one directly connected responsibility.",
            "history": [
                {
                    "role": "user",
                    "content": "Design a production model-serving stack with a monitoring component.",
                },
                {
                    "role": "assistant",
                    "content": "Initial design with gateway and router.",
                },
            ],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert called_modes == ["edit"]
    assert result["graph_data"] == existing
    assert result["graph_data"] is not existing
    assert result["graph_operation"] == {
        "kind": "edit",
        "status": "failed",
        "failure_code": "graph_edit_scope_ambiguous",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Explain RAG",
        "Do not update the current graph; explain RAG",
        "Describe the architecture",
    ],
)
async def test_unrelated_query_preserves_existing_applied_graph(monkeypatch, message):
    existing = _domain_graph(5)

    async def fail_model(**_kwargs):
        raise AssertionError("an unrelated concept query must not call a graph model")

    def fail_canonical_selection(**_kwargs):
        raise AssertionError(
            "an unrelated query must not replace an approved applied graph"
        )

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fail_model)
    monkeypatch.setattr(graph_worker, "stream_llm", fail_model)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: object())
    monkeypatch.setattr(
        graph_worker, "select_canonical_graph", fail_canonical_selection
    )

    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": False,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": message,
            "user_message": message,
            "history": [],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
        },
        [],
    )

    assert result["graph_data"] == existing


@pytest.mark.asyncio
async def test_reusing_approved_graph_emits_worker_status():
    events = []
    existing = _domain_graph(5)

    async def send(event):
        events.append(event)

    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": False,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": "Explain RAG",
            "user_message": "Explain RAG",
            "history": [],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert result["graph_data"] == existing
    assert any(
        event.get("type") == "worker_status" and event.get("worker") == "graph"
        for event in events
    )


@pytest.mark.asyncio
async def test_create_graph_does_not_require_architecture_context(monkeypatch):
    events = []

    async def send(event):
        events.append(event)

    async def fake_topology(*_args, **_kwargs):
        return {
            "graph_type": "architecture",
            "title": "Draft",
            "nodes": [{"id": "n1", "label": "Request entry"}],
            "edges": [],
            "groups": [],
            "sequence": [],
            "assumptions": [],
            "design_origin": "applied",
            "resolved_complexity": "prototype",
        }

    monkeypatch.setattr(graph_worker, "_generate_applied_architecture", fake_topology)
    result = await graph_worker.graph_worker_node(
        {
            "architecture_ready": False,
            "architect_plan": {},
            "challenger_review": {},
            "send": send,
            "design_query": "Design a resilient model-serving architecture.",
            "user_message": "Design a resilient model-serving architecture.",
            "history": [],
            "graph_data": None,
            "approved_graph_data": None,
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert result["graph_data"]["title"] == "Draft"
    assert result["graph_operation"]["status"] == "candidate"
    assert any(event.get("status") == "complete" for event in events)


@pytest.mark.asyncio
async def test_canonical_graph_edit_never_selects_an_unrelated_canonical_graph(
    monkeypatch,
):
    events = []
    canonical = {
        "design_origin": "canonical",
        "nodes": [{"id": "monitoring", "label": "Monitoring"}],
        "edges": [],
    }

    async def send(event):
        events.append(event)

    def fail_canonical_selection(**_kwargs):
        raise AssertionError("an edit must never enter canonical selection")

    monkeypatch.setattr(
        graph_worker, "select_canonical_graph", fail_canonical_selection
    )
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Expand monitoring",
            "design_query": "Expand monitoring",
            "graph_data": canonical,
            "graph_revision_count": 0,
        },
        [],
    )

    assert result["graph_data"] is None
    assert result["graph_operation"] == {
        "kind": "edit",
        "status": "failed",
        "failure_code": "graph_edit_target_unavailable",
    }
    assert any(
        event.get("failure_code") == "graph_edit_target_unavailable" for event in events
    )


@pytest.mark.asyncio
async def test_repair_attempt_preserves_the_original_create_operation(monkeypatch):
    existing = _domain_graph(5)
    candidate = copy.deepcopy(existing)
    candidate["title"] = "Repaired fulfilment architecture"

    async def generate(*_args, **_kwargs):
        return candidate

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "_generate_applied_architecture", generate)
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Design a fulfilment architecture",
            "design_query": "Design a fulfilment architecture",
            "graph_intent": "create",
            "graph_operation": {
                "kind": "create",
                "status": "candidate",
                "failure_code": None,
            },
            "graph_data": existing,
            "graph_revision_count": 1,
        },
        [],
    )

    assert result["graph_operation"] == {
        "kind": "create",
        "status": "candidate",
        "failure_code": None,
    }


@pytest.mark.asyncio
async def test_targeted_existing_graph_followup_uses_incremental_patch_lane(
    monkeypatch,
):
    existing = _domain_graph(5)
    added_edge = {
        "source": "fulfilment_stage_3",
        "target": "fulfilment_stage_1",
        "label": "returns exception for bounded recovery",
        "technology": "Typed exception event",
        "sync": "async",
        "flow": "control",
        "description": "Rejoins an exceptional carrier outcome at its owning recovery stage.",
    }
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"add_edges": [added_edge]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture(
        {
            "architecture_ready": True,
            "architect_plan": {},
            "challenger_review": {},
            "send": None,
            "user_message": (
                "Add an exception return edge from Fulfilment Stage 3 "
                "to Fulfilment Stage 1"
            ),
            "history": [],
            "graph_data": existing,
            "approved_graph_data": copy.deepcopy(existing),
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        (
            "marketplace fulfilment system add an exception return edge from "
            "Fulfilment Stage 3 to Fulfilment Stage 1"
        ),
        SimpleNamespace(resolved="prototype"),
    )

    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert len(calls) == 1
    assert calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert calls[0]["thinking_budget"] is None
    assert calls[0]["effort"] == "high"
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["allow_fallback"] is False
    assert "Source and target must be distinct" in calls[0]["system"]
    assert "immutable" in calls[0]["system"]
    assert "repair-only edge_id values" in calls[0]["system"]
    assert '"remove_edges": ["edge_2"]' in calls[0]["system"]


@pytest.mark.asyncio
async def test_first_unpublished_critic_revision_uses_incremental_patch_lane(
    monkeypatch,
):
    existing = _domain_graph(5)
    original = copy.deepcopy(existing)
    target_id = existing["nodes"][1]["id"]
    topology_calls = []
    patch_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        raise AssertionError("critic revisions must not redraw the full topology")

    async def fake_stream_llm(**kwargs):
        patch_calls.append(kwargs)
        return json.dumps(
            {
                "update_nodes": [
                    {
                        "id": target_id,
                        "set": {
                            "description": (
                                "Validates the request before the existing handoff."
                            )
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)

    updated = await graph_worker._generate_applied_architecture(
        {
            "architecture_ready": True,
            "architect_plan": {},
            "challenger_review": {},
            "complexity": "prototype",
            "graph_data": existing,
            "approved_graph_data": None,
            "graph_revision_count": 1,
            "graph_review": {
                "approved": False,
                "repair_contract": _local_repair_contract(
                    failed_layers={"components": {"node_ids": [target_id]}}
                ),
            },
            "send": None,
            "session_id": "thread-1",
            "user_id": "user-1",
            "user_message": "Repair the current candidate.",
        },
        "Design a fulfilment workflow",
        SimpleNamespace(resolved="prototype"),
    )

    assert topology_calls == []
    assert len(patch_calls) == 1
    assert patch_calls[0]["effort"] == "high"
    assert patch_calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert existing == original
    assert [node["id"] for node in updated["nodes"]] == [
        node["id"] for node in original["nodes"]
    ]
    assert (
        next(node for node in updated["nodes"] if node["id"] == target_id)[
            "description"
        ]
        == "Validates the request before the existing handoff."
    )
    assert {
        node["id"]: node for node in updated["nodes"] if node["id"] != target_id
    } == {node["id"]: node for node in original["nodes"] if node["id"] != target_id}
    assert updated.keys() == original.keys()
    for key, value in original.items():
        if key != "nodes":
            assert updated[key] == value


@pytest.mark.asyncio
async def test_production_unpublished_repair_adds_node_and_group_without_changing_existing_groups(
    monkeypatch,
):
    existing = _domain_graph(9, production=True)
    before = copy.deepcopy(existing)
    groups = copy.deepcopy(existing["groups"])
    groups.append(
        {
            "id": "exception_reconciliation",
            "label": "Exception reconciliation",
            "kind": "operations",
            "nodeIds": ["exception_reconciler"],
        }
    )
    patch_calls = []
    topology_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        raise AssertionError("critic repair must not regenerate the topology")

    async def fake_stream_llm(**kwargs):
        patch_calls.append(kwargs)
        return json.dumps(
            {
                "add_nodes": [
                    {
                        "id": "exception_reconciler",
                        "label": "Exception Reconciler",
                        "type": "service",
                        "technology": "Versioned reconciliation worker",
                        "description": "Owns bounded fulfilment exception reconciliation.",
                    }
                ],
                "add_edges": [
                    {
                        "source": "fulfilment_stage_7",
                        "target": "exception_reconciler",
                        "label": "routes unresolved delivery exception",
                        "technology": "Versioned exception event",
                        "sync": "async",
                        "flow": "control",
                        "description": "Routes the unresolved exception to its bounded owner.",
                    },
                    {
                        "source": "exception_reconciler",
                        "target": "fulfilment_stage_2",
                        "label": "returns reconciled parcel state",
                        "technology": "Versioned parcel event",
                        "sync": "async",
                        "flow": "control",
                        "description": "Returns reconciled state to the existing runtime path.",
                    },
                ],
                "groups": groups,
            }
        )

    contract = _local_repair_contract(
        failed_layers={
            "components": {
                "addition_count": 1,
                "context_node_ids": [
                    "fulfilment_stage_7",
                    "fulfilment_stage_2",
                ],
            },
            "connections": {
                "addition_count": 2,
                "context_node_ids": [
                    "fulfilment_stage_7",
                    "fulfilment_stage_2",
                ],
                "connection_addition_obligations": [
                    {
                        "source": "fulfilment_stage_7",
                        "target": "$new_node_1",
                        "required_contract": "routes unresolved delivery exception",
                    },
                    {
                        "source": "$new_node_1",
                        "target": "fulfilment_stage_2",
                        "required_contract": "returns reconciled parcel state",
                    },
                ],
            },
            "composition": {
                "composition_fields": ["groups"],
                "composition_append_counts": {"groups": 1},
            },
        }
    )
    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)

    updated = await graph_worker._generate_applied_architecture(
        {
            "architecture_ready": True,
            "architect_plan": {},
            "challenger_review": {},
            "complexity": "production",
            "graph_data": existing,
            "approved_graph_data": None,
            "graph_revision_count": 1,
            "graph_review": {"approved": False, "repair_contract": contract},
            "send": None,
            "session_id": "thread-1",
            "user_id": "user-1",
            "user_message": "Repair the unpublished production candidate.",
        },
        "Design a production fulfilment workflow",
        SimpleNamespace(resolved="production"),
    )

    assert topology_calls == []
    assert len(patch_calls) == 1
    assert existing == before
    assert any(node["id"] == "exception_reconciler" for node in updated["nodes"])
    reconciler = next(
        node for node in updated["nodes"] if node["id"] == "exception_reconciler"
    )
    assert reconciler["tier"] is None
    assert reconciler["lane"] == "bottom"
    assert updated["groups"][: len(before["groups"])] == before["groups"]
    assert updated["groups"][-1] == {
        "id": "exception_reconciliation",
        "label": "Exception reconciliation",
        "kind": "operations",
        "nodeIds": ["exception_reconciler"],
    }
    prompt = patch_calls[0]["messages"][0]["content"]
    assert '"repair_scope": "local"' in prompt
    assert "60%" not in prompt


@pytest.mark.asyncio
async def test_current_production_profile_can_refine_legacy_nine_node_graph(
    monkeypatch,
):
    existing = _domain_graph(9, production=True)
    added_edge = {
        "source": "fulfilment_stage_7",
        "target": "fulfilment_stage_2",
        "label": "returns carrier dispute for reviewed recovery",
        "technology": "Typed dispute event",
        "sync": "async",
        "flow": "control",
        "description": "Routes a carrier dispute to the existing review owner without expanding the graph.",
    }
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"add_edges": [added_edge]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    profile = resolve_complexity("production", "Design a production fulfilment system")

    result = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": (
                "Connect Fulfilment Stage 7 to Fulfilment Stage 2 for carrier dispute recovery"
            ),
            "graph_review": {},
            "complexity": "production",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Connect Fulfilment Stage 7 to Fulfilment Stage 2 for carrier dispute recovery",
        profile,
        existing,
    )

    assert len(calls) == 1
    assert len(result["nodes"]) == 9
    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert "within 9-13 nodes" not in calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_invalid_initial_json_stops_without_correction(
    monkeypatch,
):
    calls = []

    async def fake_stream_structured_llm(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="not-json", finish_reason="end_turn")

    async def send(_event):
        return None

    monkeypatch.setattr(
        graph_worker, "stream_structured_llm", fake_stream_structured_llm
    )
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "design_query": "Design an AI marketplace fulfilment system architecture",
            "user_message": "Design an AI marketplace fulfilment system architecture",
            "history": [],
            "graph_data": None,
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "architect_plan": {},
            "challenger_review": {},
            "architecture_ready": True,
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        [],
    )

    assert result["graph_data"] is None
    assert len(calls) == 1
    assert calls[0]["telemetry"]["metadata"]["model_role"] == "structured_topology"


@pytest.mark.asyncio
async def test_invalid_patch_preserves_approved_graph_without_duplicate_model_call(
    monkeypatch,
):
    existing = _domain_graph(5)
    approved = copy.deepcopy(existing)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"remove_nodes": ["fulfilment_stage_2"]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Repair the failed parcel exception path",
                "history": [],
                "graph_data": existing,
                "graph_revision_count": 1,
                "graph_review": {
                    "approved": False,
                    "repair_contract": _local_repair_contract(
                        failed_layers={
                            "components": {"node_ids": ["fulfilment_stage_2"]},
                        }
                    ),
                },
                "complexity": "prototype",
                "research_context": "",
                "rag_chunks": [],
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Repair the failed parcel exception path",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"
    assert existing == approved
    assert len(calls) == 1
    assert calls[0]["model"] == graph_worker.settings.graph_builder_model
    assert calls[0]["timeout_seconds"] == graph_worker.settings.graph_patch_timeout_s
    assert (
        calls[0]["max_output_tokens"]
        == graph_worker.settings.graph_builder_max_completion_tokens
    )
    assert calls[0]["effort"] == "high"
    assert calls[0]["thinking_budget"] is None
    assert "only the minimal patch" in calls[0]["messages"][0]["content"]
    assert "at most 8 total operations" not in calls[0]["messages"][0]["content"]
    assert "Never return a replacement graph" in calls[0]["system"]
    assert "Map every blocking finding" in calls[0]["system"]
    assert "read-only global topology skeleton" in calls[0]["system"]
    assert "server permissions are the complete" in calls[0]["system"]
    assert "complete source, target, and label triple" in calls[0]["system"]
    assert "post-patch critic verifies the" in calls[0]["system"]
    assert "does not supply omitted behavior" in calls[0]["system"]
    assert "approval-only route" not in calls[0]["system"]
    assert calls[0]["telemetry"]["metadata"]["prompt_version"] == (
        graph_worker._APPLIED_GRAPH_PATCH_PROMPT_VERSION
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("patch_output", "expected_rule"),
    [
        ('{"add_edges": [', "json_decode"),
        ("[]", "invalid_shape"),
    ],
)
async def test_invalid_patch_json_provides_contract_correction_coordinates(
    monkeypatch,
    patch_output,
    expected_rule,
):
    existing = _domain_graph(5)

    async def fake_stream_llm(**_kwargs):
        return patch_output

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)

    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Repair the failed parcel exception path",
                "graph_data": existing,
                "graph_revision_count": 1,
                "graph_review": {
                    "approved": False,
                    "repair_contract": _local_repair_contract(
                        failed_layers={
                            "components": {"node_ids": ["fulfilment_stage_2"]},
                        }
                    ),
                },
                "complexity": "prototype",
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Repair the failed parcel exception path",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"
    assert raised.value.path == "patch"
    assert raised.value.rule == expected_rule


@pytest.mark.parametrize(
    ("message", "expected_rule"),
    [
        (
            "added edge is outside the named connection scope",
            "outside_named_connection_scope",
        ),
    ],
)
def test_added_edge_scope_failures_provide_contract_correction_coordinates(
    message,
    expected_rule,
):
    assert graph_worker._patch_validation_coordinates(ValueError(message)) == (
        "patch.add_edges",
        expected_rule,
    )


@pytest.mark.asyncio
async def test_multi_region_exact_record_repair_preserves_uncited_records(monkeypatch):
    existing = _domain_graph(15, production=True)
    before = copy.deepcopy(existing)
    edge_selectors = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": edge["label"],
        }
        for edge in (existing["edges"][0], existing["edges"][8])
    ]
    calls = []

    async def patch_disconnected_edges(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "update_edges": [
                    {
                        "edge_id": "edge_1",
                        "set": {
                            "description": "Carries the corrected intake contract."
                        },
                    },
                    {
                        "edge_id": "edge_9",
                        "set": {
                            "description": "Carries the corrected outcome contract."
                        },
                    },
                ]
            }
        )

    monkeypatch.setattr(graph_worker, "stream_llm", patch_disconnected_edges)
    updated = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": "Repair the broad runtime chain",
            "graph_revision_count": 1,
            "graph_review": {
                "approved": False,
                "repair_contract": _local_repair_contract(
                    failed_layers={"connections": {"edge_selectors": edge_selectors}}
                ),
            },
            "complexity": "prototype",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Repair the broad runtime chain",
        SimpleNamespace(resolved="prototype"),
        existing,
    )

    assert len(calls) == 1
    assert existing == before
    assert (
        updated["edges"][0]["description"] == "Carries the corrected intake contract."
    )
    assert (
        updated["edges"][8]["description"] == "Carries the corrected outcome contract."
    )
    assert updated["edges"][1:8] == before["edges"][1:8]
    assert updated["edges"][9:] == before["edges"][9:]
    assert updated["nodes"] == before["nodes"]
    assert updated["groups"] == before["groups"]
    assert updated["sequence"] == before["sequence"]


@pytest.mark.asyncio
async def test_unanchored_component_additions_never_call_the_patch_model(monkeypatch):
    existing = _domain_graph(5)
    contract = _local_repair_contract(
        failed_layers={
            "components": {"addition_count": 2},
            "connections": {"addition_count": 1},
        }
    )
    calls = []

    async def fail_if_called(**kwargs):
        calls.append(kwargs)
        raise AssertionError("patch model must not run")

    monkeypatch.setattr(graph_worker, "stream_llm", fail_if_called)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Add the missing subsystem",
                "graph_revision_count": 1,
                "graph_review": {
                    "approved": False,
                    "repair_contract": contract,
                },
                "complexity": "prototype",
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Add the missing subsystem",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_patch_contract_invalid"
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_self_edge_patch_preserves_graph_without_duplicate_model_call(
    monkeypatch,
):
    existing = _domain_graph(5)
    approved = copy.deepcopy(existing)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "add_edges": [
                    {
                        "source": "fulfilment_stage_3",
                        "target": "fulfilment_stage_3",
                        "label": "retries generation internally",
                        "technology": "Typed retry event",
                        "sync": "async",
                        "flow": "control",
                        "description": "Retries generation inside the same responsibility.",
                    }
                ]
            }
        )

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    with pytest.raises(graph_worker.GraphPatchRejected) as raised:
        await graph_worker._generate_applied_architecture_patch(
            {
                "send": None,
                "user_message": "Make failure recovery explicit",
                "graph_review": {
                    "approved": False,
                    "repair_contract": _local_repair_contract(
                        failed_layers={
                            "connections": {
                                "addition_count": 1,
                                "context_node_ids": [
                                    "fulfilment_stage_2",
                                    "fulfilment_stage_3",
                                ],
                            }
                        },
                    ),
                },
                "complexity": "prototype",
                "graph_revision_count": 1,
                "user_id": "user-1",
                "session_id": "thread-1",
            },
            "Make failure recovery explicit in this fulfilment system",
            SimpleNamespace(resolved="prototype"),
            existing,
        )

    assert raised.value.code == "graph_patch_invalid_preserved_existing_graph"
    assert existing == approved
    assert len(calls) == 1
    assert calls[0]["effort"] == "high"
    assert calls[0]["telemetry"]["metadata"]["patch_attempt"] == 0


def test_local_contract_canonicalization_repairs_book_technology_and_edge_label(caplog):
    graph = _domain_graph(5)
    original_node = copy.deepcopy(graph["nodes"][0])
    graph["nodes"][0]["technology"] = "Book method"
    graph["edges"][0]["label"] = ["passes", "verified parcel state"]

    with caplog.at_level("INFO", logger=graph_worker.__name__):
        result = graph_worker._normalise_applied_graph_candidate(
            graph,
            safety_max_nodes=5,
            resolved_complexity="prototype",
            context="unit.initial",
        )

    assert result["nodes"][0]["technology"] == "Application service"
    assert result["nodes"][0]["label"] == original_node["label"]
    assert result["nodes"][0]["description"] == original_node["description"]
    assert result["edges"][0]["label"] == "passes / verified parcel state"
    assert "node_index=0" in caplog.text
    assert "value_type=list" in caplog.text


def test_patch_contract_canonicalization_repairs_node_technology_and_edge_label():
    existing = _domain_graph(5)
    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_2",
                    "set": {"technology": "Book objective"},
                }
            ],
            "add_edges": [
                {
                    "source": "fulfilment_stage_3",
                    "target": "fulfilment_stage_1",
                    "label": ("routes carrier failure", "to recovery owner"),
                    "technology": "Typed failure event",
                    "sync": "async",
                    "flow": "control",
                    "description": "Routes a failed carrier operation to its distinct recovery owner.",
                }
            ],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    repaired_node = next(
        node for node in result["nodes"] if node["id"] == "fulfilment_stage_2"
    )
    assert repaired_node["technology"] == "Application service"
    assert result["edges"][-1]["label"] == "routes carrier failure / to recovery owner"


@pytest.mark.parametrize(
    ("label", "expected", "action"),
    [
        (
            "  routes  verified\nparcel\tstate  ",
            "routes verified parcel state",
            "normalize_whitespace",
        ),
        (
            (
                "routes verified parcel state to recovery owner after deterministic policy, "
                "approval before execution with durable audit attribution"
            ),
            (
                "routes verified parcel state to recovery owner after deterministic policy, "
                "approval before execution"
            ),
            "truncate_word_boundary",
        ),
    ],
)
def test_string_edge_label_canonicalization_is_bounded_and_content_free(
    label,
    expected,
    action,
    caplog,
):
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = label

    with caplog.at_level("INFO", logger=graph_worker.__name__):
        result = graph_worker._normalise_applied_graph_candidate(
            graph,
            safety_max_nodes=5,
            resolved_complexity="prototype",
            context="unit.string-label",
        )

    assert result["edges"][0]["label"] == expected
    assert f"original_length={len(label)}" in caplog.text
    assert f"action={action}" in caplog.text
    assert label not in caplog.text


def test_patch_string_edge_label_canonicalization_changes_only_authored_values():
    overlong = (
        "routes verified parcel state to recovery owner after deterministic policy, "
        "approval before execution with durable audit attribution"
    )
    result = graph_worker._canonicalise_applied_graph_patch(
        {
            "add_edges": [{"label": "  adds  verified route  "}],
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {"label": overlong},
                }
            ],
            "remove_edges": ["edge_2"],
        }
    )

    assert result["add_edges"][0]["label"] == "adds verified route"
    assert result["update_edges"][0]["edge_id"] == "edge_1"
    assert result["update_edges"][0]["set"]["label"] == (
        "routes verified parcel state to recovery owner after deterministic policy, "
        "approval before execution"
    )
    assert result["remove_edges"] == ["edge_2"]


def test_blank_update_values_are_omitted_while_other_changes_remain():
    result = graph_worker._canonicalise_applied_graph_patch(
        {
            "update_nodes": [
                {
                    "id": "gate",
                    "set": {"technology": None, "description": "Retains node detail."},
                }
            ],
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {
                        "label": " \t ",
                        "technology": "",
                        "description": "Retains the authored detail.",
                    },
                }
            ],
        }
    )

    assert result["update_nodes"][0]["set"] == {
        "description": "Retains node detail.",
    }
    assert result["update_edges"][0]["set"] == {
        "description": "Retains the authored detail.",
    }


def test_new_patch_records_use_initial_topology_presentation_defaults():
    result = graph_worker._canonicalise_applied_graph_patch(
        {
            "add_nodes": [
                {
                    "id": "policy_gate",
                    "label": "Policy Gate",
                    "type": "decision",
                    "technology": " ",
                    "description": None,
                }
            ],
            "add_edges": [
                {
                    "source": "policy_gate",
                    "target": "audit_store",
                    "label": "records rejected decision",
                    "technology": "",
                    "description": None,
                    "flow": "feedback",
                }
            ],
        }
    )

    assert result["add_nodes"][0]["technology"] == "Auditable decision gate"
    assert result["add_nodes"][0]["description"] == "Policy Gate"
    assert result["add_edges"][0]["technology"] == "Versioned feedback event"
    assert result["add_edges"][0]["description"] == "records rejected decision"


def test_patch_applies_new_edge_with_blank_presentation_fields():
    graph = _domain_graph(5)

    result = graph_worker._apply_applied_graph_patch(
        graph,
        {
            "add_edges": [
                {
                    "source": "fulfilment_stage_2",
                    "target": "fulfilment_stage_0",
                    "label": "routes rejected parcel to intake",
                    "technology": " ",
                    "sync": "async",
                    "flow": "control",
                    "description": None,
                }
            ],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    added = next(
        edge
        for edge in result["edges"]
        if edge["label"] == "routes rejected parcel to intake"
    )
    assert added["technology"] == "Typed control signal"
    assert added["description"] == added["label"]


def test_blank_update_label_that_empties_set_is_rejected():
    graph = _domain_graph(5)

    with pytest.raises(ValueError, match="edge update set must be a non-empty object"):
        graph_worker._apply_applied_graph_patch(
            graph,
            {
                "update_edges": [
                    {
                        "edge_id": "edge_1",
                        "set": {"label": " "},
                    }
                ],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


def test_patch_preserves_existing_labels_at_graph_contract_limit():
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = "x" * 100

    result = graph_worker._apply_applied_graph_patch(
        graph,
        {
            "update_nodes": [
                {
                    "id": "fulfilment_stage_0",
                    "set": {"description": "Owns the bounded marketplace intake."},
                }
            ],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert result["edges"][0]["label"] == "x" * 100


@pytest.mark.parametrize("label", [" \t\n "])
def test_string_edge_label_canonicalization_rejects_unsafe_values(label):
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = label

    with pytest.raises(ValueError, match="bounded exact string"):
        graph_worker._normalise_applied_graph_candidate(
            graph,
            safety_max_nodes=5,
            resolved_complexity="prototype",
            context="unit.unsafe-string-label",
        )


def test_unbroken_authored_edge_label_uses_deterministic_hard_boundary():
    result = graph_worker._canonicalise_applied_graph_patch(
        {
            "add_edges": [{"label": "x" * 101}],
            "update_edges": [
                {
                    "edge_id": "edge_1",
                    "set": {"label": "y" * 101},
                }
            ],
            "remove_edges": ["edge_2"],
        }
    )

    assert result["add_edges"][0]["label"] == "x" * 100
    assert result["update_edges"][0]["edge_id"] == "edge_1"
    assert result["update_edges"][0]["set"]["label"] == "y" * 100
    assert result["remove_edges"] == ["edge_2"]


@pytest.mark.parametrize("label", [None, " \t "])
def test_add_edge_missing_or_blank_label_recovers_only_from_description(label):
    existing = _domain_graph(5)
    edge = {
        "source": "fulfilment_stage_3",
        "target": "fulfilment_stage_1",
        "technology": "Typed failure event",
        "sync": "async",
        "flow": "control",
        "description": "routes carrier failure to the recovery owner",
    }
    if label is not None:
        edge["label"] = label

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {"add_edges": [edge]},
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert result["edges"][-1]["label"] == edge["description"]


@pytest.mark.parametrize(
    "edge",
    [
        {"source": "fulfilment_stage_3", "target": "fulfilment_stage_1"},
        {
            "source": "fulfilment_stage_3",
            "target": "fulfilment_stage_1",
            "label": " ",
            "description": " \t ",
        },
    ],
)
def test_add_edge_without_authored_label_or_description_fails_closed(edge):
    with pytest.raises(ValueError, match="non-empty label or non-empty description"):
        graph_worker._canonicalise_applied_graph_patch({"add_edges": [edge]})


@pytest.mark.parametrize("missing_field", ["source", "target"])
def test_add_edge_requires_both_endpoints(missing_field):
    existing = _domain_graph(5)
    edge = {
        "source": "fulfilment_stage_3",
        "target": "fulfilment_stage_1",
        "label": "routes carrier failure to recovery",
        "technology": "Typed failure event",
        "sync": "async",
        "flow": "control",
        "description": "Routes carrier failure to its recovery owner.",
    }
    edge.pop(missing_field)

    with pytest.raises(
        ValueError, match="added edge requires source, target, and label"
    ):
        graph_worker._apply_applied_graph_patch(
            existing,
            {"add_edges": [edge]},
            safety_max_nodes=7,
            resolved_complexity="prototype",
        )


@pytest.mark.parametrize(
    "invalid_label",
    [
        {},
        42,
        [],
        ["valid", ""],
        ["one", "two", "three", "four", "five"],
    ],
)
def test_local_contract_canonicalization_rejects_other_edge_label_shapes(invalid_label):
    graph = _domain_graph(5)
    graph["edges"][0]["label"] = invalid_label

    with pytest.raises(ValueError, match="bounded non-empty string list"):
        graph_worker._normalise_applied_graph_candidate(
            graph,
            safety_max_nodes=5,
            resolved_complexity="prototype",
            context="unit.invalid-label",
        )


def _one_node_over_budget_graph():
    graph = _domain_graph(6)
    graph["groups"] = [
        {
            "id": "intake",
            "label": "Marketplace Intake",
            "kind": "runtime",
            "nodeIds": ["fulfilment_stage_0", "fulfilment_stage_1"],
        },
        {
            "id": "execution",
            "label": "Fulfilment Execution",
            "kind": "runtime",
            "nodeIds": [
                "fulfilment_stage_2",
                "fulfilment_stage_3",
                "fulfilment_stage_4",
                "fulfilment_stage_5",
            ],
        },
    ]
    graph["sequence"] = [
        {
            "step": 1,
            "nodes": ["fulfilment_stage_0"],
            "description": "Accepts the marketplace request.",
        },
        {
            "step": 2,
            "nodes": ["fulfilment_stage_0", "fulfilment_stage_1"],
            "description": "Routes accepted marketplace work.",
        },
    ]
    return graph


def test_one_node_over_safety_ceiling_is_rejected_without_compaction(monkeypatch):
    graph = _one_node_over_budget_graph()
    publication_checks = []

    def accept_publication(query, candidate, resolved_complexity):
        publication_checks.append((query, candidate, resolved_complexity))

    monkeypatch.setattr(
        graph_worker,
        "_validate_applied_architecture_patch",
        accept_publication,
    )
    with pytest.raises(
        ValueError,
        match="exceeds its 5-node resource-safety ceiling; got 6",
    ):
        graph_worker._normalise_applied_graph_candidate(
            graph,
            safety_max_nodes=5,
            resolved_complexity="prototype",
            context="unit.node-safety-rejection",
        )

    assert publication_checks == []


@pytest.mark.asyncio
async def test_semantic_patch_defects_are_left_for_independent_model_review(
    monkeypatch,
):
    existing = _domain_graph(9, production=True)
    collapsed_edge = {
        "source": "fulfilment_stage_7",
        "target": "fulfilment_stage_2",
        "label": "returns COMMITTED / NOT_FOUND / STILL_UNKNOWN state",
        "technology": "Lifecycle read-back",
        "sync": "async",
        "flow": "control",
        "description": "Returns the external outcome state for reconciliation.",
    }
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"add_edges": [collapsed_edge]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": (
                "Add a reconciliation edge from Fulfilment Stage 7 "
                "to Fulfilment Stage 2"
            ),
            "graph_review": {
                "approved": False,
                "revision_instruction": "Split each reconciliation outcome.",
            },
            "complexity": "production",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        (
            "Add a reconciliation edge from Fulfilment Stage 7 to "
            "Fulfilment Stage 2 in this fulfilment system"
        ),
        SimpleNamespace(resolved="production"),
        existing,
    )

    assert len(calls) == 1
    assert result["edges"][-1]["label"] == collapsed_edge["label"]
    assert result != existing
    graph_worker._validate_applied_architecture_patch(
        "Make reconciliation branches explicit in this fulfilment system",
        result,
        "production",
    )


def test_self_loop_edges_are_rejected_without_silent_deletion(monkeypatch):
    candidate = _domain_graph(5)
    self_loop = copy.deepcopy(candidate["edges"][0])
    self_loop["source"] = candidate["nodes"][0]["id"]
    self_loop["target"] = candidate["nodes"][0]["id"]
    candidate["edges"].append(self_loop)
    validations: list[tuple[object, ...]] = []

    def accept_publication(*args):
        validations.append(args)

    monkeypatch.setattr(
        graph_worker,
        "_validate_applied_architecture_patch",
        accept_publication,
    )

    with pytest.raises(ValueError, match="graph edges cannot point a node to itself"):
        graph_worker._normalise_applied_graph_candidate(
            candidate,
            safety_max_nodes=12,
            resolved_complexity="standard",
            context="self-loop rejection test",
        )

    assert validations == []


def test_self_loop_removal_fails_closed_when_publication_topology_is_invalid(
    monkeypatch,
):
    candidate = _domain_graph(5)
    self_loop = copy.deepcopy(candidate["edges"][0])
    self_loop["source"] = candidate["nodes"][0]["id"]
    self_loop["target"] = candidate["nodes"][0]["id"]
    candidate["edges"].append(self_loop)

    def reject_publication(*_args):
        raise ValueError("topology remains invalid")

    monkeypatch.setattr(
        graph_worker,
        "_validate_applied_architecture_patch",
        reject_publication,
    )

    with pytest.raises(ValueError, match="graph edges cannot point a node to itself"):
        graph_worker._normalise_applied_graph_candidate(
            candidate,
            safety_max_nodes=12,
            resolved_complexity="standard",
            context="self-loop rejection test",
        )
