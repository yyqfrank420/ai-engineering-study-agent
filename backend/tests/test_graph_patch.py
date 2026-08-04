import copy
import json
from types import SimpleNamespace

import pytest

from agent.complexity import resolve_complexity
from agent.nodes import graph_worker


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
        min_nodes=node_count,
        max_nodes=node_count,
        resolved_complexity="production" if production else "prototype",
    )


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
        min_nodes=5,
        max_nodes=5,
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
        min_nodes=5,
        max_nodes=7,
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
                "tier": "private",
                "lane": "main",
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
        min_nodes=9,
        max_nodes=12,
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


def test_patch_updates_nodes_and_edges_and_removes_only_selected_edge():
    existing = _domain_graph(5)
    removed_edge = existing["edges"][-1]
    updated_edge = existing["edges"][1]
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
                "match": {
                    "source": updated_edge["source"],
                    "target": updated_edge["target"],
                    "label": updated_edge["label"],
                },
                "set": {
                    "label": "passes customs-ready parcel state",
                    "technology": "Signed customs envelope",
                },
            }
        ],
        "remove_edges": [
            {
                "source": removed_edge["source"],
                "target": removed_edge["target"],
                "label": removed_edge["label"],
            }
        ],
    }

    result = graph_worker._apply_applied_graph_patch(
        existing,
        patch,
        min_nodes=5,
        max_nodes=7,
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


def test_patch_selector_accepts_copied_known_edge_metadata():
    existing = _domain_graph(5)
    removed_edge = existing["edges"][-1]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {"remove_edges": [{
            key: removed_edge.get(key)
            for key in graph_worker._PATCH_EDGE_FIELDS
        }]},
        min_nodes=5,
        max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(result["edges"]) == len(existing["edges"]) - 1
    assert not any(
        edge["source"] == removed_edge["source"]
        and edge["target"] == removed_edge["target"]
        and edge["label"] == removed_edge["label"]
        for edge in result["edges"]
    )


def test_patch_selector_accepts_unambiguous_match_wrapper():
    existing = _domain_graph(5)
    removed_edge = existing["edges"][-1]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {"remove_edges": [{"match": {
            "source": removed_edge["source"],
            "target": removed_edge["target"],
            "label": removed_edge["label"],
        }}]},
        min_nodes=5,
        max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(result["edges"]) == len(existing["edges"]) - 1


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
        min_nodes=5,
        max_nodes=7,
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
            min_nodes=5,
            max_nodes=7,
            resolved_complexity="prototype",
        )

    assert existing == before


def test_patch_cannot_replace_most_of_an_approved_graph():
    existing = _domain_graph(5)
    incident_edges = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "label": edge["label"],
        }
        for edge in existing["edges"]
        if edge["source"] in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
        or edge["target"] in {"fulfilment_stage_2", "fulfilment_stage_3", "fulfilment_stage_4"}
    ]

    with pytest.raises(ValueError, match="preserve at least 60%"):
        graph_worker._apply_applied_graph_patch(
            existing,
            {
                "remove_nodes": [
                    "fulfilment_stage_2",
                    "fulfilment_stage_3",
                    "fulfilment_stage_4",
                ],
                "remove_edges": incident_edges,
            },
            min_nodes=2,
            max_nodes=7,
            resolved_complexity="prototype",
        )


def test_over_budget_edges_are_rejected_before_position_can_manufacture_isolation():
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

    with pytest.raises(ValueError, match="20-edge readability budget; got 21"):
        graph_worker._normalise_applied_graph(
            payload,
            min_nodes=9,
            max_nodes=9,
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
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )
    target = existing["edges"][0]

    result = graph_worker._apply_applied_graph_patch(
        existing,
        {
            "update_edges": [{
                "match": {
                    "source": target["source"],
                    "target": target["target"],
                    "label": target["label"],
                },
                "set": {"flow": "feedback", "type": "loop"},
            }]
        },
        min_nodes=9,
        max_nodes=9,
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
            min_nodes=5,
            max_nodes=7,
            resolved_complexity="prototype",
        )


def test_message_queue_is_a_supported_architecture_primitive():
    graph = _domain_graph(5)
    graph["nodes"][2]["type"] = "queue"
    graph["nodes"][2]["technology"] = "Durable event stream"

    normalised = graph_worker._normalise_applied_graph(
        graph,
        min_nodes=5,
        max_nodes=7,
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
        min_nodes=5,
        max_nodes=7,
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
        min_nodes=5,
        max_nodes=7,
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
        min_nodes=5,
        max_nodes=7,
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
        min_nodes=5,
        max_nodes=7,
        resolved_complexity="prototype",
    )

    assert normalised["edges"][0]["technology"] == "Canary/promoted deployment"


def _release_graph_for_completion():
    graph = _domain_graph(9, production=True)
    graph["nodes"][5].update({"label": "Release Controller", "type": "control"})
    graph["nodes"][6].update({"label": "Campaign Runtime", "type": "service"})
    graph["nodes"][7].update({"label": "Event Definition Registry", "type": "datastore"})
    graph["edges"].extend([
        {
            "source": "fulfilment_stage_5",
            "target": "fulfilment_stage_6",
            "label": "deploy canary release",
            "technology": "Immutable release manifest",
            "sync": "async",
            "flow": "deployment",
            "description": "Activates the evaluated release in a bounded canary lane.",
        },
        {
            "source": "fulfilment_stage_5",
            "target": "fulfilment_stage_6",
            "label": "promote full production release",
            "technology": "Reviewed release decision",
            "sync": "async",
            "flow": "deployment",
            "description": "Activates the canary-approved immutable release for all traffic.",
        },
        {
            "source": "fulfilment_stage_7",
            "target": "fulfilment_stage_5",
            "label": "supply immutable evaluated release",
            "technology": "Versioned release manifest",
            "sync": "async",
            "flow": "deployment",
            "description": "Supplies the release controller with one immutable evaluated version.",
        },
    ])
    return graph_worker._normalise_applied_graph(
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )


def test_deterministic_completion_adds_only_missing_release_rollback():
    graph = _release_graph_for_completion()

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is not None
    assert len(completed["edges"]) == len(graph["edges"]) + 1
    assert any(
        edge["label"] == "rollback to prior approved release"
        and edge["source"] == "fulfilment_stage_5"
        and edge["target"] == "fulfilment_stage_7"
        and edge["flow"] == "deployment"
        for edge in completed["edges"]
    )
    graph_worker._validate_applied_architecture_patch(
        "Design a production model release workflow",
        completed,
        "production",
    )


def test_deterministic_completion_allows_service_owner_without_registry():
    graph = _release_graph_for_completion()
    graph["nodes"][5].update({"label": "Evaluation Release Ops", "type": "service"})
    graph["nodes"][7]["label"] = "Evaluated Release Archive"

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is not None
    assert any(
        edge["label"] == "rollback to prior approved release"
        and edge["source"] == "fulfilment_stage_5"
        and edge["target"] == "fulfilment_stage_6"
        for edge in completed["edges"]
    )


def test_deterministic_completion_does_not_hide_other_review_failures():
    graph = _domain_graph(9, production=True)

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is None


def test_deterministic_completion_fails_closed_at_edge_budget():
    graph = _release_graph_for_completion()
    while len(graph["edges"]) < graph_worker._edge_budget(9):
        index = len(graph["edges"])
        graph["edges"].append({
            "source": f"fulfilment_stage_{index % 9}",
            "target": f"fulfilment_stage_{(index + 2) % 9}",
            "label": f"carry bounded release evidence {index}",
            "technology": "Typed release evidence",
            "sync": "async",
            "flow": "control",
            "description": "Carries one bounded release observation to its review owner.",
        })
    graph = graph_worker._normalise_applied_graph(
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is None


@pytest.mark.parametrize("failure_mode", ["ambiguous_promotion", "non_deployment"])
def test_deterministic_completion_requires_unique_typed_release_topology(failure_mode):
    graph = _release_graph_for_completion()
    promotion = next(
        edge for edge in graph["edges"] if edge["label"] == "promote full production release"
    )
    if failure_mode == "ambiguous_promotion":
        graph["edges"].append({
            **promotion,
            "label": "promote full production event definitions",
        })
    else:
        promotion["flow"] = "control"
    graph = graph_worker._normalise_applied_graph(
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is None


@pytest.mark.parametrize("failure_mode", ["ambiguous_owner", "different_targets"])
def test_deterministic_completion_requires_one_owner_and_shared_target(failure_mode):
    graph = _release_graph_for_completion()
    promotion = next(
        edge for edge in graph["edges"] if edge["label"] == "promote full production release"
    )
    if failure_mode == "ambiguous_owner":
        canary = next(
            edge for edge in graph["edges"] if edge["label"] == "deploy canary release"
        )
        graph["nodes"][4].update({"label": "Secondary Release Ops", "type": "service"})
        graph["edges"].extend([
            {**canary, "source": "fulfilment_stage_4"},
            {**promotion, "source": "fulfilment_stage_4"},
        ])
    else:
        promotion["target"] = "fulfilment_stage_8"
    graph = graph_worker._normalise_applied_graph(
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    completed = graph_worker._complete_missing_release_rollback(
        "Design a production model release workflow",
        graph,
        min_nodes=9,
        max_nodes=9,
        resolved_complexity="production",
    )

    assert completed is None


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
        min_nodes=5,
        max_nodes=7,
        resolved_complexity="prototype",
    )

    assert len(normalised["edges"]) == len(graph["edges"])


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
            "send": None,
            "user_message": "Expand the exception return paths",
            "history": [],
            "graph_data": existing,
            "graph_revision_count": 0,
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "marketplace fulfilment system expand the exception return paths",
        SimpleNamespace(
            resolved="prototype",
            min_graph_nodes=5,
            max_graph_nodes=7,
            answer_contract="A coherent bounded domain loop.",
            thinking_budget=4096,
        ),
    )

    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert len(calls) == 1
    assert calls[0]["telemetry"]["metadata"]["model_role"] == "incremental_patch"
    assert calls[0]["thinking_budget"] is None
    assert calls[0]["effort"] == "medium"
    assert "Source and target must be distinct" in calls[0]["system"]


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
    assert "within 9-13 nodes" in calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_invalid_patch_preserves_approved_graph_after_bounded_retry(monkeypatch):
    existing = _domain_graph(5)
    approved = copy.deepcopy(existing)
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({"remove_nodes": ["fulfilment_stage_2"]})

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture(
        {
            "send": None,
            "user_message": "Repair the failed parcel exception path",
            "history": [],
            "graph_data": existing,
            "graph_revision_count": 1,
            "graph_review": {
                "approved": False,
                "revision_instruction": "Close the exception branch without replacing the graph.",
            },
            "complexity": "prototype",
            "research_context": "",
            "rag_chunks": [],
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Repair the failed parcel exception path",
        SimpleNamespace(
            resolved="prototype",
            min_graph_nodes=5,
            max_graph_nodes=7,
            answer_contract="A coherent bounded domain loop.",
            thinking_budget=None,
        ),
    )

    assert result == approved
    assert existing == approved
    assert len(calls) == 2
    assert calls[0]["model"] == graph_worker.settings.orchestrator_model
    assert calls[0]["effort"] == "low"
    assert calls[1]["effort"] == "medium"
    assert calls[0]["thinking_budget"] is None
    assert "Never return a replacement graph" in calls[0]["system"]
    assert "map every supplied blocking failure" in calls[0]["system"]
    assert "The approval-only route must explicitly say" in calls[0]["system"]
    assert "Human review, a manual lane, escalation, or hold alone" in calls[0]["system"]
    assert "the promotion edge must not mention" in calls[0]["system"]
    assert calls[0]["telemetry"]["metadata"]["prompt_version"] == (
        graph_worker._APPLIED_GRAPH_PATCH_PROMPT_VERSION
    )


@pytest.mark.asyncio
async def test_invalid_self_edge_patch_gets_one_validation_informed_retry(monkeypatch):
    existing = _domain_graph(5)
    valid_edge = {
        "source": "fulfilment_stage_3",
        "target": "fulfilment_stage_1",
        "label": "routes generation failure to recovery owner",
        "technology": "Typed failure event",
        "sync": "async",
        "flow": "control",
        "description": "A distinct recovery owner handles bounded retry without a self-edge.",
    }
    responses = [
        {
            "add_edges": [{
                **valid_edge,
                "source": "fulfilment_stage_3",
                "target": "fulfilment_stage_3",
            }]
        },
        {"add_edges": [valid_edge]},
    ]
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps(responses[len(calls) - 1])

    monkeypatch.setattr(graph_worker, "stream_llm", fake_stream_llm)
    result = await graph_worker._generate_applied_architecture_patch(
        {
            "send": None,
            "user_message": "Make failure recovery explicit",
            "graph_review": {
                "approved": False,
                "revision_instruction": "Separate generation failure from evaluation rejection.",
            },
            "complexity": "prototype",
            "graph_revision_count": 1,
            "user_id": "user-1",
            "session_id": "thread-1",
        },
        "Make failure recovery explicit in this fulfilment system",
        SimpleNamespace(resolved="prototype", min_graph_nodes=5, max_graph_nodes=7),
        existing,
    )

    assert len(calls) == 2
    assert len(result["edges"]) == len(existing["edges"]) + 1
    assert "self-referencing edge is not allowed" in calls[1]["messages"][0]["content"]
    assert '"source": "fulfilment_stage_3"' in calls[1]["messages"][0]["content"]
    assert "Rejected patch (untrusted data" in calls[1]["messages"][0]["content"]
    assert calls[0]["effort"] == "low"
    assert calls[1]["effort"] == "medium"
    assert calls[1]["telemetry"]["metadata"]["patch_attempt"] == 1


@pytest.mark.asyncio
async def test_semantically_ineffective_patch_reaches_canonical_workflow_review(monkeypatch):
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
        SimpleNamespace(resolved="production", min_graph_nodes=9, max_graph_nodes=13),
        existing,
    )

    assert len(calls) == 1
    assert result["edges"][-1]["label"] == collapsed_edge["label"]
    assert result != existing
    with pytest.raises(ValueError, match="Draw committed, not-found retry"):
        graph_worker._validate_applied_architecture_patch(
            "Make reconciliation branches explicit in this fulfilment system",
            result,
            "production",
        )
