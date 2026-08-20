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
    validate_create_connection_correction_authority,
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


def test_create_connection_correction_allows_control_endpoint():
    rejected = assign_server_ids(_plan())
    corrected = copy.deepcopy(rejected)
    corrected["connections"].append(
        {
            "source_id": "n1",
            "target_id": "n2",
            "label": "requests authorization status",
            "flow": "control",
            "sync": "sync",
        }
    )

    accepted = validate_create_connection_correction_authority(rejected, corrected)

    assert accepted["connections"][-1]["flow"] == "control"


def test_create_connection_correction_rejects_control_edge_without_authority():
    rejected = assign_server_ids(_plan())
    corrected = copy.deepcopy(rejected)
    corrected["connections"].append(
        {
            "source_id": "n1",
            "target_id": "n3",
            "label": "controls ledger state",
            "flow": "control",
            "sync": "sync",
        }
    )

    with pytest.raises(GraphContractError, match="control or decision") as error:
        validate_create_connection_correction_authority(rejected, corrected)

    assert error.value.path == "connections"


def test_create_connection_correction_rejects_runtime_to_control_without_authority():
    rejected = _plan()
    rejected["connections"].append(
        {
            "source_id": "0",
            "target_id": "2",
            "label": "records payment request",
            "flow": "runtime",
            "sync": "sync",
        }
    )
    rejected = assign_server_ids(rejected)
    corrected = copy.deepcopy(rejected)
    corrected["connections"][-1]["flow"] = "control"

    with pytest.raises(GraphContractError, match="control or decision") as error:
        validate_create_connection_correction_authority(rejected, corrected)

    assert error.value.path == "connections"


def test_create_connection_correction_cannot_change_components():
    rejected = assign_server_ids(_plan())
    corrected = copy.deepcopy(rejected)
    corrected["components"][0]["type"] = "control"

    with pytest.raises(GraphContractError, match="cannot change components") as error:
        validate_create_connection_correction_authority(rejected, corrected)

    assert error.value.path == "components"
