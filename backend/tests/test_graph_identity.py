import json

from agent.graph_identity import applied_edge_metadata
from agent.nodes.graph_worker import (
    _apply_applied_graph_patch,
    _normalise_applied_graph,
)
from agent.staged_graph_contract import (
    project_graph_data,
    reconstruct_staged_graph_build,
)


def _build(labels):
    return {
        "request_id": "edge-identity-test",
        "title": "Payment authorization",
        "assumptions": [],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "components": [
            {
                "model_index": index,
                "label": label,
                "type": "service",
                "responsibility": responsibility,
                "group_label": "Runtime",
                "group_kind": "runtime",
                "primary_flow_member": True,
            }
            for index, label, responsibility in [
                (0, "Payment client", "Submits payment requests."),
                (1, "Payment policy", "Validates payment requests."),
            ]
        ],
        "connections": [
            {
                "source_id": "0",
                "target_id": "1",
                "label": label,
                "flow": "runtime",
                "sync": "sync",
            }
            for label in labels
        ],
        "maturity": "prototype",
        "source": "test",
        "stage": "planned",
    }


def _normalize(graph):
    return _normalise_applied_graph(
        graph, safety_max_nodes=10, resolved_complexity="prototype"
    )


def test_distinct_labels_keep_distinct_stable_identities_across_creation_paths():
    labels = [
        "a" * 64 + "alpha",
        "a" * 64 + "beta",
        "sends-payment",
        "sends payment",
        "支付授权",
        "记录审计",
    ]
    graph = project_graph_data(_build(labels))
    normalized = _normalize(graph)

    for candidate in [graph, normalized]:
        assert len(candidate["edges"]) == len(labels)
        assert len({edge["edge_id"] for edge in candidate["edges"]}) == len(labels)
        assert all(len(edge["relation"]) <= 64 for edge in candidate["edges"])
        assert all(edge["relation"].isascii() for edge in candidate["edges"])
    assert normalized["edges"] == graph["edges"]
    assert _normalize(normalized) == normalized
    assert project_graph_data(reconstruct_staged_graph_build(graph)) == graph


def test_identity_normalizes_case_and_outer_whitespace_without_unicode_casefold_collision():
    assert applied_edge_metadata("n1", "n2", " Sends payment ") == (
        applied_edge_metadata("n1", "n2", "sends payment")
    )
    assert applied_edge_metadata("n1", "n2", "Straße") != applied_edge_metadata(
        "n1", "n2", "STRASSE"
    )
    assert applied_edge_metadata("n1", "n2", "支付授权")["relation"].startswith(
        "relation_"
    )


def test_stored_legacy_identity_survives_repeated_edits_and_label_change_gets_new_identity():
    graph = project_graph_data(_build(["submits payment"]))
    graph["edges"][0].update(edge_id="applied:legacy-edge", relation="legacy_relation")
    stored = json.loads(json.dumps(graph))

    for revision in range(2):
        stored = _apply_applied_graph_patch(
            stored,
            {
                "update_nodes": [
                    {
                        "id": "n2",
                        "set": {
                            "description": f"Validates payment revision {revision}."
                        },
                    }
                ]
            },
            safety_max_nodes=10,
            resolved_complexity="prototype",
        )
        assert stored["edges"] == graph["edges"]

    changed = _apply_applied_graph_patch(
        stored,
        {
            "update_edges": [
                {"edge_id": "edge_1", "set": {"label": "requests authorization"}}
            ]
        },
        safety_max_nodes=10,
        resolved_complexity="prototype",
    )
    assert {
        key: changed["edges"][0][key] for key in ("edge_id", "relation")
    } == applied_edge_metadata("n1", "n2", "requests authorization")
