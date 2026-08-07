import copy
import json
from types import SimpleNamespace

import pytest

from agent.complexity import resolve_complexity
from agent.nodes import graph_worker


def test_patch_accepts_multiple_operations_when_final_graph_remains_safe():
    graph = _domain_graph(5)
    patch = {
        "update_nodes": [
            {
                "id": node["id"],
                "set": {"description": f"Keeps bounded responsibility {index}."},
            }
            for index, node in enumerate(graph["nodes"])
        ],
        "update_edges": [
            {
                "edge_id": f"edge_{index}",
                "set": {"description": f"Keeps bounded transition {index}."},
            }
            for index, _edge in enumerate(graph["edges"], start=1)
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


def test_graph_design_json_failure_is_classified_as_truncated():
    exc = json.JSONDecodeError("Unterminated string", "{", 1)

    assert graph_worker._graph_design_failure_code(exc) == "graph_design_output_truncated"


def test_graph_timeouts_and_invalid_patches_have_distinct_failure_codes():
    assert graph_worker._graph_design_failure_code(
        TimeoutError("deadline exhausted")
    ) == "graph_design_timeout"
    assert graph_worker._graph_patch_failure_code(
        TimeoutError("deadline exhausted")
    ) == "graph_patch_timeout_preserved_existing_graph"
    assert graph_worker._graph_patch_failure_code(
        ValueError("unknown graph patch field")
    ) == "graph_patch_invalid_preserved_existing_graph"


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


def test_patch_topology_context_includes_every_mutable_graph_layer():
    context = json.loads(graph_worker._format_patch_topology({
        "title": "Bounded graph",
        "assumptions": ["The policy store supports version reads."],
        "groups": [{"id": "runtime"}],
        "sequence": [{"step": 1, "nodes": ["gate"], "description": "Review."}],
        "nodes": [{
            "id": "gate",
            "label": "Approval Gate",
            "type": "decision",
            "description": "Routes approved and rejected outcomes.",
            "technology": "Policy rules engine",
        }],
        "edges": [{
            "source": "gate",
            "target": "ledger",
            "label": "persist rejection",
            "flow": "control",
            "sync": "async",
            "type": "loop",
            "description": "Durable terminal outcome.",
            "technology": "Signed decision record",
        }],
    }))

    assert set(context) == {
        "title", "nodes", "edges", "groups", "sequence", "assumptions",
    }
    assert context["groups"] == [{"id": "runtime"}]
    assert context["sequence"][0]["nodes"] == ["gate"]
    assert context["assumptions"] == ["The policy store supports version reads."]
    assert set(context["nodes"][0]) == {
        "id", *graph_worker._PATCH_NODE_MUTABLE_FIELDS,
    }
    assert set(context["edges"][0]) == {
        "edge_id", *graph_worker._PATCH_EDGE_MUTABLE_FIELDS,
    }
    assert context["nodes"][0]["technology"] == "Policy rules engine"
    assert context["nodes"][0]["description"] == (
        "Routes approved and rejected outcomes."
    )
    assert context["edges"][0]["technology"] == "Signed decision record"
    assert context["edges"][0]["description"] == "Durable terminal outcome."
    assert context["edges"][0]["edge_id"] == "edge_1"


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
                "nodeIds": [f"fulfilment_stage_{index}" for index in range(6, node_count)],
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
    return {"repair_scope": "local", "layers": layers}


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
    assert next(node for node in result["nodes"] if node["id"] == "fulfilment_stage_7") == next(
        node for node in before["nodes"] if node["id"] == "fulfilment_stage_7"
    )
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
    cache = next(node for node in result["nodes"] if node["id"] == "carrier_quote_cache")
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

    updated_node = next(node for node in result["nodes"] if node["id"] == "fulfilment_stage_2")
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
    existing["edges"].append({
        **copy.deepcopy(first),
        "label": "distinct route over the same node pair",
    })

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
            "update_nodes": [{
                "id": "fulfilment_stage_2",
                "set": {"label": "Customs Evidence Check"},
            }],
            "add_edges": None,
            "title": None,
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert result["title"] == existing["title"]
    assert next(
        node for node in result["nodes"] if node["id"] == "fulfilment_stage_2"
    )["label"] == "Customs Evidence Check"


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
        if edge["source"] in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
        or edge["target"] in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
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
        "fulfilment_stage_0", "fulfilment_stage_1",
    ]


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
                "update_nodes": [{
                    "id": "fulfilment_stage_1",
                    "set": {"description": "Out-of-scope mutation."},
                }],
            },
            safety_max_nodes=7,
            resolved_complexity="prototype",
            repair_contract=contract,
        )

    assert existing == before


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
    } == {
        field: before[field] for field in graph_worker._PATCH_NODE_MUTABLE_FIELDS
    }


@pytest.mark.parametrize(
    ("field", "selectors", "replacement"),
    [
        (
            "sequence",
            {"sequence_indexes": [0]},
            [
                {"step": 1, "nodes": ["fulfilment_stage_0"], "description": "Allowed."},
                {"step": 2, "nodes": ["fulfilment_stage_1"], "description": "Locked edit."},
                {"step": 3, "nodes": ["fulfilment_stage_2"], "description": "Runs observable marketplace step 3."},
                {"step": 4, "nodes": ["fulfilment_stage_3"], "description": "Runs observable marketplace step 4."},
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


def test_over_resource_safety_edges_are_rejected_before_position_can_hide_isolation(monkeypatch):
    existing = _domain_graph(9, production=True)
    payload = copy.deepcopy(existing)
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if "fulfilment_stage_8" not in {edge["source"], edge["target"]}
    ]
    while len(payload["edges"]) < 20:
        index = len(payload["edges"])
        payload["edges"].append({
            "source": f"fulfilment_stage_{index % 7}",
            "target": f"fulfilment_stage_{(index + 2) % 8}",
            "label": f"carries auxiliary recovery signal {index}",
            "technology": "Typed recovery event",
            "sync": "async",
            "flow": "control",
            "description": "Carries a bounded recovery signal without changing the main path.",
        })
    payload["edges"].append({
        "source": "fulfilment_stage_7",
        "target": "fulfilment_stage_8",
        "label": "connects the final recovery owner",
        "technology": "Typed recovery event",
        "sync": "async",
        "flow": "control",
        "description": "Keeps the final owner connected even when listed last.",
    })

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
        existing["edges"].append({
            "source": "fulfilment_stage_0",
            "target": "fulfilment_stage_8",
            "label": f"carries bounded exception signal {index}",
            "technology": "Typed exception event",
            "sync": "async",
            "flow": "control",
            "description": "Carries a bounded exception signal to its recovery owner.",
        })
    existing = graph_worker._normalise_applied_graph(
        existing,
        safety_max_nodes=9,
        resolved_complexity="production",
    )
    target = existing["edges"][0]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_edges": [{
                "edge_id": "edge_1",
                "set": {"flow": "feedback", "type": "loop"},
            }]
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
                "update_nodes": [{
                    "id": "fulfilment_stage_2",
                    "set": {"label": "Fulfilment Stage 2"},
                }]
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
    graph["edges"][0].update({
        "label": "auto-route pre-approved bounded action",
        "technology": "Signed payload and target envelope",
        "description": (
            "Binds the policy version, expiry, and idempotency key before durable reservation."
        ),
    })

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["label"] == "auto-route pre-approved bounded action"


def test_graph_parser_preserves_collapsed_outcomes_for_critic_repair():
    graph = _domain_graph(5)
    graph["edges"][0].update({
        "label": "reconcile operation status",
        "technology": "Authoritative read-back",
        "description": "Returns COMMITTED, NOT_FOUND, or STILL_UNKNOWN as one result.",
    })

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["label"] == "reconcile operation status"


def test_graph_parser_preserves_combined_deployment_edge_for_critic_repair():
    graph = _domain_graph(5)
    graph["edges"][0].update({
        "label": "deploy release",
        "technology": "Canary/promoted deployment",
        "description": "Routes either stage into the same runtime transition.",
    })

    normalised = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["technology"] == "Canary/promoted deployment"


def test_graph_parser_keeps_independent_control_defects_for_one_critic_review():
    graph = _domain_graph(5)
    graph["edges"][0].update({
        "label": "deploy release",
        "technology": "Canary/promoted deployment",
        "description": "Routes either stage into the same runtime transition.",
    })
    graph["edges"][1].update({
        "label": "reconcile operation status",
        "technology": "Authoritative read-back",
        "description": "Returns COMMITTED, NOT_FOUND, or STILL_UNKNOWN as one result.",
    })

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
        "Fix the typo in the cache label",
        "Rename the cache node",
        "Remove the stale edge",
        "Change the edge label",
        "Redesign this edge",
        "Redesign the cache group",
        "Redesign the whole architecture from scratch with a fraud node",
        "Replace the entire diagram while keeping the title",
        "Do not redesign the whole graph; only update this edge",
        "Update this edge without redesigning the whole graph",
        "Redesign this edge to show the complete architecture flow",
        "Redesign the cache group so the whole graph remains clear",
        "Rebuild the cache node",
        "Start over with the graph",
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
        return json.dumps({
            "update_nodes": [
                {
                    "id": target_id,
                    "set": {"description": "Owns the corrected cache responsibility."},
                }
            ]
        })

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
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
    assert next(node for node in result["graph_data"]["nodes"] if node["id"] == target_id)[
        "description"
    ] == "Owns the corrected cache responsibility."


@pytest.mark.asyncio
async def test_new_applied_topic_replaces_instead_of_patching_existing_graph(monkeypatch):
    existing = _domain_graph(5)
    topology_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        return SimpleNamespace(text="not-json", finish_reason="end_turn")

    async def fail_patch(**_kwargs):
        raise AssertionError("a new system request must not patch the prior domain")

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
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
        raise AssertionError("an unrelated query must not replace an approved applied graph")

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fail_model)
    monkeypatch.setattr(graph_worker, "stream_llm", fail_model)
    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: object())
    monkeypatch.setattr(graph_worker, "select_canonical_graph", fail_canonical_selection)

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
async def test_targeted_existing_graph_followup_uses_incremental_patch_lane(monkeypatch):
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
            "user_message": "Expand the exception return edges",
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
        "marketplace fulfilment system expand the exception return edges",
        SimpleNamespace(resolved="prototype"),
    )

    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert len(calls) == 1
    assert calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert calls[0]["thinking_budget"] is None
    assert calls[0]["effort"] == "max"
    assert "Source and target must be distinct" in calls[0]["system"]
    assert "immutable repair-only edge_id" in calls[0]["system"]
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

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
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
    assert patch_calls[0]["effort"] == "max"
    assert patch_calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert existing == original
    assert [node["id"] for node in updated["nodes"]] == [
        node["id"] for node in original["nodes"]
    ]
    assert next(node for node in updated["nodes"] if node["id"] == target_id)[
        "description"
    ] == "Validates the request before the existing handoff."
    assert {
        node["id"]: node for node in updated["nodes"] if node["id"] != target_id
    } == {
        node["id"]: node for node in original["nodes"] if node["id"] != target_id
    }
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
    groups.append({
        "id": "exception_reconciliation",
        "label": "Exception reconciliation",
        "kind": "operations",
        "nodeIds": ["exception_reconciler"],
    })
    patch_calls = []
    topology_calls = []

    async def fake_stream_structured_llm(**kwargs):
        topology_calls.append(kwargs)
        raise AssertionError("critic repair must not regenerate the topology")

    async def fake_stream_llm(**kwargs):
        patch_calls.append(kwargs)
        return json.dumps({
            "add_nodes": [{
                "id": "exception_reconciler",
                "label": "Exception Reconciler",
                "type": "service",
                "technology": "Versioned reconciliation worker",
                "description": "Owns bounded fulfilment exception reconciliation.",
            }],
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
        })

    contract = _local_repair_contract(
        failed_layers={
            "components": {},
            "connections": {},
            "composition": {
                "composition_fields": ["groups"],
            },
        }
    )
    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
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
async def test_current_production_profile_can_refine_legacy_nine_node_graph(monkeypatch):
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
            "user_message": "Expand carrier dispute recovery",
            "graph_review": {},
            "complexity": "production",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Expand carrier dispute recovery in this fulfilment system",
        profile,
        existing,
    )

    assert len(calls) == 1
    assert len(result["nodes"]) == 9
    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert "within 9-13 nodes" not in calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_invalid_initial_design_fails_closed_without_duplicate_model_call(monkeypatch):
    calls = []

    async def fake_stream_structured_llm(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="not-json", finish_reason="end_turn")

    async def send(_event):
        return None

    monkeypatch.setattr(graph_worker, "stream_structured_llm", fake_stream_structured_llm)
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
async def test_invalid_patch_preserves_approved_graph_without_duplicate_model_call(monkeypatch):
    existing = _domain_graph(5)
    approved = copy.deepcopy(existing)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"remove_nodes": ["fulfilment_stage_2"]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture_patch(
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

    assert result == approved
    assert existing == approved
    assert result is not existing
    assert len(calls) == 1
    assert calls[0]["model"] == graph_worker.settings.graph_builder_model
    assert calls[0]["timeout_seconds"] == graph_worker.settings.graph_patch_timeout_s
    assert (
        calls[0]["max_output_tokens"]
        == graph_worker.settings.graph_builder_max_completion_tokens
    )
    assert calls[0]["effort"] == "max"
    assert calls[0]["thinking_budget"] is None
    assert "only the minimal patch" in calls[0]["messages"][0]["content"]
    assert "at most 8 total operations" not in calls[0]["messages"][0]["content"]
    assert "Never return a replacement graph" in calls[0]["system"]
    assert "map every supplied blocking failure" in calls[0]["system"]
    assert "The approval-only route must explicitly say" in calls[0]["system"]
    assert "Human review, a manual lane, escalation, or hold alone" in calls[0]["system"]
    assert "the promotion edge must not mention" in calls[0]["system"]
    assert calls[0]["telemetry"]["metadata"]["prompt_version"] == (
        graph_worker._APPLIED_GRAPH_PATCH_PROMPT_VERSION
    )


@pytest.mark.asyncio
async def test_invalid_self_edge_patch_preserves_graph_without_duplicate_model_call(monkeypatch):
    existing = _domain_graph(5)
    approved = copy.deepcopy(existing)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({
            "add_edges": [{
                "source": "fulfilment_stage_3",
                "target": "fulfilment_stage_3",
                "label": "retries generation internally",
                "technology": "Typed retry event",
                "sync": "async",
                "flow": "control",
                "description": "Retries generation inside the same responsibility.",
            }]
        })

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": "Make failure recovery explicit",
            "graph_review": {
                "approved": False,
                "repair_contract": _local_repair_contract(
                    failed_layers={"connections": {}},
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

    assert result == approved
    assert existing == approved
    assert result is not existing
    assert len(calls) == 1
    assert calls[0]["effort"] == "max"
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
            "update_nodes": [{
                "id": "fulfilment_stage_2",
                "set": {"technology": "Book objective"},
            }],
            "add_edges": [{
                "source": "fulfilment_stage_3",
                "target": "fulfilment_stage_1",
                "label": ("routes carrier failure", "to recovery owner"),
                "technology": "Typed failure event",
                "sync": "async",
                "flow": "control",
                "description": "Routes a failed carrier operation to its distinct recovery owner.",
            }],
        },
        safety_max_nodes=7,
        resolved_complexity="prototype",
    )

    repaired_node = next(node for node in result["nodes"] if node["id"] == "fulfilment_stage_2")
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
            "routes verified parcel state to recovery owner after deterministic policy, "
            "approval before execution with durable audit attribution",
            "routes verified parcel state to recovery owner after deterministic policy, "
            "approval before execution",
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
    result = graph_worker._canonicalise_applied_graph_patch({
        "add_edges": [{"label": "  adds  verified route  "}],
        "update_edges": [{
            "edge_id": "edge_1",
            "set": {"label": overlong},
        }],
        "remove_edges": ["edge_2"],
    })

    assert result["add_edges"][0]["label"] == "adds verified route"
    assert result["update_edges"][0]["edge_id"] == "edge_1"
    assert result["update_edges"][0]["set"]["label"] == (
        "routes verified parcel state to recovery owner after deterministic policy, "
        "approval before execution"
    )
    assert result["remove_edges"] == ["edge_2"]


def test_blank_update_values_are_omitted_while_other_changes_remain():
    result = graph_worker._canonicalise_applied_graph_patch({
        "update_nodes": [{
            "id": "gate",
            "set": {"technology": None, "description": "Retains node detail."},
        }],
        "update_edges": [{
            "edge_id": "edge_1",
            "set": {
                "label": " \t ",
                "technology": "",
                "description": "Retains the authored detail.",
            },
        }],
    })

    assert result["update_nodes"][0]["set"] == {
        "description": "Retains node detail.",
    }
    assert result["update_edges"][0]["set"] == {
        "description": "Retains the authored detail.",
    }


def test_new_patch_records_use_initial_topology_presentation_defaults():
    result = graph_worker._canonicalise_applied_graph_patch({
        "add_nodes": [{
            "id": "policy_gate",
            "label": "Policy Gate",
            "type": "decision",
            "technology": " ",
            "description": None,
        }],
        "add_edges": [{
            "source": "policy_gate",
            "target": "audit_store",
            "label": "records rejected decision",
            "technology": "",
            "description": None,
            "flow": "feedback",
        }],
    })

    assert result["add_nodes"][0]["technology"] == "Auditable decision gate"
    assert result["add_nodes"][0]["description"] == "Policy Gate"
    assert result["add_edges"][0]["technology"] == "Versioned feedback event"
    assert result["add_edges"][0]["description"] == "records rejected decision"


def test_patch_applies_new_edge_with_blank_presentation_fields():
    graph = _domain_graph(5)

    result = graph_worker._apply_applied_graph_patch(
        graph,
        {
            "add_edges": [{
                "source": "fulfilment_stage_2",
                "target": "fulfilment_stage_0",
                "label": "routes rejected parcel to intake",
                "technology": " ",
                "sync": "async",
                "flow": "control",
                "description": None,
            }],
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
                "update_edges": [{
                    "edge_id": "edge_1",
                    "set": {"label": " "},
                }],
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
            "update_nodes": [{
                "id": "fulfilment_stage_0",
                "set": {"description": "Owns the bounded marketplace intake."},
            }],
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
    result = graph_worker._canonicalise_applied_graph_patch({
        "add_edges": [{"label": "x" * 101}],
        "update_edges": [{
            "edge_id": "edge_1",
            "set": {"label": "y" * 101},
        }],
        "remove_edges": ["edge_2"],
    })

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

    with pytest.raises(ValueError, match="added edge requires source, target, and label"):
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
async def test_semantic_patch_defects_are_left_for_independent_model_review(monkeypatch):
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
            "user_message": "Make reconciliation branches explicit",
            "graph_review": {
                "approved": False,
                "revision_instruction": "Split each reconciliation outcome.",
            },
            "complexity": "production",
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Make reconciliation branches explicit in this fulfilment system",
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


def test_self_loop_removal_fails_closed_when_publication_topology_is_invalid(monkeypatch):
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
