import copy

import pytest

from agent.staged_graph_contract import (
    GraphContractError,
    assign_server_ids,
    component_fingerprint,
    connection_fingerprint,
    derive_groups,
    production_proofs_for_capabilities,
    project_graph_data,
    reconstruct_staged_graph_build,
    validate_component_write_set,
    validate_connection_write_set,
    validate_staged_graph_build,
)


def _plan():
    return {
        "request_id": "request-1",
        "title": "Payment authorization",
        "assumptions": ["The ledger is authoritative."],
        "root_index": 0,
        "capabilities": {
            "external_effects": True,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "components": [
            {
                "model_index": 0,
                "label": "Client",
                "type": "client",
                "responsibility": "Submits a payment request.",
                "group_label": "Runtime",
                "group_kind": "runtime",
                "primary_flow_member": True,
            },
            {
                "model_index": 1,
                "label": "Policy gate",
                "type": "control",
                "responsibility": "Authorizes the requested payment.",
                "group_label": "Runtime",
                "group_kind": "runtime",
                "primary_flow_member": True,
            },
            {
                "model_index": 2,
                "label": "Payment ledger",
                "type": "datastore",
                "responsibility": "Records the authoritative payment state.",
                "group_label": "Data",
                "group_kind": "data",
                "primary_flow_member": True,
            },
        ],
        "connections": [
            {
                "source_id": "0",
                "target_id": "1",
                "label": "submits payment",
                "flow": "runtime",
                "sync": "sync",
            },
            {
                "source_id": "1",
                "target_id": "2",
                "label": "records authorization",
                "flow": "control",
                "sync": "sync",
            },
        ],
        "maturity": "production",
        "source": "test",
        "stage": "planned",
    }


def test_assign_project_and_reconstruct_are_stable():
    assigned = assign_server_ids(_plan())
    assert [component["server_id"] for component in assigned["components"]] == [
        "n1",
        "n2",
        "n3",
    ]
    graph = project_graph_data(assigned)
    assert graph["sequence"] == [
        {"step": 1, "nodes": ["n1"], "description": "Primary flow stage 1"},
        {"step": 2, "nodes": ["n2"], "description": "Primary flow stage 2"},
        {"step": 3, "nodes": ["n3"], "description": "Primary flow stage 3"},
    ]
    assert graph["groups"] == [
        {
            "id": "group_runtime",
            "label": "Runtime",
            "kind": "runtime",
            "nodeIds": ["n1", "n2"],
        },
        {"id": "group_data", "label": "Data", "kind": "data", "nodeIds": ["n3"]},
    ]
    reconstructed = reconstruct_staged_graph_build(graph, assigned)
    assert project_graph_data(reconstructed) == graph


@pytest.mark.parametrize(
    ("node_type", "technology"),
    [
        ("client", "Client"),
        ("service", "Application service"),
        ("datastore", "Data store"),
        ("queue", "Message queue"),
        ("gateway", "Gateway"),
        ("network", "Network"),
        ("external", "External system"),
        ("control", "Control component"),
        ("decision", "Decision component"),
    ],
)
def test_node_projection_describes_type_without_inventing_guarantees(
    node_type, technology
):
    plan = _plan()
    plan["components"][0].update(
        type=node_type,
        responsibility="Submits a request.",
    )

    node = project_graph_data(plan)["nodes"][0]

    assert node["technology"] == technology
    assert node["description"] == "Submits a request."


@pytest.mark.parametrize(
    ("flow", "technology"),
    [
        ("runtime", "Runtime flow"),
        ("control", "Control flow"),
        ("feedback", "Feedback flow"),
        ("deployment", "Deployment flow"),
    ],
)
def test_edge_projection_describes_flow_without_inventing_guarantees(flow, technology):
    plan = _plan()
    plan["connections"].append(
        {
            "source_id": "0",
            "target_id": "2",
            "label": "sends a request",
            "flow": flow,
            "sync": "async",
        }
    )

    edge = project_graph_data(plan)["edges"][-1]

    assert edge["technology"] == technology
    assert edge["description"] == "sends a request"


def test_existing_group_id_is_retained():
    plan = assign_server_ids(_plan())
    groups = derive_groups(
        plan,
        existing_groups=[
            {
                "id": "runtime-zone",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["old"],
            }
        ],
    )
    assert groups[0]["id"] == "runtime-zone"


def test_primary_members_must_be_reachable_over_runtime_or_control_edges():
    plan = _plan()
    plan["connections"][1]["flow"] = "feedback"
    with pytest.raises(GraphContractError, match="must be reachable"):
        validate_staged_graph_build(assign_server_ids(plan))


def test_nonprimary_transit_keeps_walkthrough_steps_contiguous_and_parallel():
    plan = _plan()
    plan["components"][1]["primary_flow_member"] = False
    plan["components"].append(
        {**plan["components"][2], "model_index": 3, "label": "Receipt ledger"}
    )
    plan["connections"].extend(
        [
            {**plan["connections"][1], "target_id": "3"},
            {**plan["connections"][0], "source_id": "2", "target_id": "1"},
        ]
    )

    graph = project_graph_data(plan)

    assert graph["sequence"] == [
        {"step": 1, "nodes": ["n1"], "description": "Primary flow stage 1"},
        {"step": 2, "nodes": ["n3", "n4"], "description": "Primary flow stage 2"},
    ]
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 4
    assert graph["groups"][0]["nodeIds"] == ["n1", "n2"]
    assert project_graph_data(reconstruct_staged_graph_build(graph)) == graph


@pytest.mark.parametrize("flow", ["feedback", "deployment"])
def test_nonprimary_transit_cannot_use_nonruntime_contracts(flow):
    plan = _plan()
    plan["components"][1]["primary_flow_member"] = False
    plan["connections"][1]["flow"] = flow

    with pytest.raises(GraphContractError, match="must be reachable"):
        project_graph_data(plan)


def test_component_label_and_type_pairs_must_be_unique():
    plan = _plan()
    plan["components"][1]["label"] = plan["components"][0]["label"].upper()
    plan["components"][1]["type"] = plan["components"][0]["type"]

    with pytest.raises(GraphContractError, match="label and type pairs must be unique"):
        assign_server_ids(plan)


def test_production_proof_mapping_and_fingerprints_are_deterministic():
    capabilities = _plan()["capabilities"]
    assert production_proofs_for_capabilities(capabilities, maturity="prototype") == []
    assert production_proofs_for_capabilities(capabilities, maturity="production") == [
        "audit_and_provenance",
        "authorization_and_compensation",
        "state_effect_reconciliation",
    ]
    first = assign_server_ids(_plan())
    second = assign_server_ids(copy.deepcopy(_plan()))
    assert component_fingerprint(first) == component_fingerprint(second)
    assert connection_fingerprint(first) == connection_fingerprint(second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Revised payment authorization"),
        ("assumptions", ["Payment requests arrive from a trusted caller."]),
        ("root_index", 1),
        (
            "capabilities",
            {
                "external_effects": False,
                "retrieval_or_reuse": True,
                "learning_or_release": False,
            },
        ),
        ("maturity", "prototype"),
    ],
)
def test_component_fingerprint_includes_reviewed_candidate_context(field, value):
    base = assign_server_ids(_plan())
    candidate = copy.deepcopy(base)
    candidate[field] = value

    assert component_fingerprint(candidate) != component_fingerprint(base)


def test_component_fingerprint_ignores_later_connections_and_request_metadata():
    base = assign_server_ids(_plan())
    candidate = copy.deepcopy(base)
    candidate["connections"] = []
    candidate["request_id"] = "another-request"
    candidate["stage"] = "components"

    assert component_fingerprint(candidate) == component_fingerprint(base)


def test_write_sets_reject_uncited_component_and_connection_changes():
    base = assign_server_ids(_plan())
    component_candidate = copy.deepcopy(base)
    component_candidate["components"][1]["label"] = "Authorization gate"
    with pytest.raises(GraphContractError, match="uncited component"):
        validate_component_write_set(
            base,
            component_candidate,
            {
                "allowed_ids": [],
                "addition_count": 0,
                "removal_count": 0,
                "incident_edge_ids": [],
            },
        )
    connection_candidate = copy.deepcopy(base)
    connection_candidate["connections"][0]["label"] = "submits approved payment"
    with pytest.raises(GraphContractError, match="uncited connection"):
        validate_connection_write_set(
            base,
            connection_candidate,
            {
                "allowed_ids": [],
                "addition_count": 1,
                "removal_count": 1,
                "incident_edge_ids": [],
            },
        )


def test_component_deletion_accepts_reindexing_with_exact_incident_authority():
    base = assign_server_ids(_plan())
    candidate = copy.deepcopy(base)
    candidate["components"].pop(1)
    candidate["components"][1]["model_index"] = 1
    candidate["connections"] = []
    before = copy.deepcopy(base)

    accepted = validate_component_write_set(
        base,
        candidate,
        {
            "allowed_ids": ["n2"],
            "removal_count": 1,
            "incident_edge_ids": [
                "n1|n2|submits payment",
                "n2|n3|records authorization",
            ],
        },
    )

    assert [component["server_id"] for component in accepted["components"]] == [
        "n1",
        "n3",
    ]
    assert accepted["components"][1] == {**base["components"][2], "model_index": 1}
    assert base == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", "Different ledger"),
        ("type", "service"),
        ("responsibility", "Owns different records."),
        ("group_label", "Different group"),
        ("group_kind", "runtime"),
        ("primary_flow_member", False),
    ],
)
def test_component_deletion_rejects_mutating_a_reindexed_survivor(field, value):
    base = assign_server_ids(_plan())
    candidate = copy.deepcopy(base)
    candidate["components"].pop(1)
    candidate["components"][1].update(model_index=1, **{field: value})
    candidate["connections"] = []

    with pytest.raises(GraphContractError, match="changes an uncited component"):
        validate_component_write_set(
            base,
            candidate,
            {
                "allowed_ids": ["n2"],
                "removal_count": 1,
                "incident_edge_ids": [
                    "n1|n2|submits payment",
                    "n2|n3|records authorization",
                ],
            },
        )


def test_component_deletion_cannot_remove_incident_edges_without_edge_authority():
    base = assign_server_ids(_plan())
    candidate = copy.deepcopy(base)
    candidate["components"].pop(1)
    candidate["components"][1]["model_index"] = 1
    candidate["connections"] = []

    with pytest.raises(GraphContractError, match="incident edge without authority"):
        validate_component_write_set(
            base, candidate, {"allowed_ids": ["n2"], "removal_count": 1}
        )


def test_control_flow_does_not_require_control_or_decision_component_types():
    plan = _plan()
    plan["components"][1]["type"] = "service"
    before = copy.deepcopy(plan)

    accepted = validate_staged_graph_build(assign_server_ids(plan))

    assert (
        accepted["components"][1]["responsibility"]
        == "Authorizes the requested payment."
    )
    assert accepted["components"][1]["type"] == "service"
    assert accepted["components"][2]["type"] == "datastore"
    assert accepted["connections"][1] == {
        "source_id": "n2",
        "target_id": "n3",
        "label": "records authorization",
        "flow": "control",
        "sync": "sync",
    }
    assert plan == before
