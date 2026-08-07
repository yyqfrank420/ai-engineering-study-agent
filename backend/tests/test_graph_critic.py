import json

import pytest
from config import settings

from agent.nodes.graph_critic import (
    _GRAPH_CRITIC_PROMPT_VERSION,
    _GRAPH_CRITIC_PROTOCOL_RETRY_MIN_REMAINING_S,
    _GRAPH_CRITIC_SYSTEM,
    _TOPOLOGY_PROOF_GUARANTEES,
    _deterministic_render_review,
    _validate_review_protocol,
    _deterministic_review,
    _merge_reviews,
    _normalise_review,
    _normalise_topology_proofs,
    graph_critic_node,
)


def test_semantic_critic_rejects_cache_replay_or_retry_gate_bypasses():
    assert _GRAPH_CRITIC_PROMPT_VERSION == "architecture_critic_v26"
    assert "gate-preserving reuse" in _GRAPH_CRITIC_SYSTEM
    assert "reuse stores accepted" in _GRAPH_CRITIC_SYSTEM
    assert "post-gate artifacts" in _GRAPH_CRITIC_SYSTEM
    assert "rejoins the gate" in _GRAPH_CRITIC_SYSTEM
    assert "inspect directed paths, not vocabulary" in _GRAPH_CRITIC_SYSTEM
    assert "Carrying a retry key is not durable" in _GRAPH_CRITIC_SYSTEM
    assert "Rejection stops before execution and is not compensation" in _GRAPH_CRITIC_SYSTEM
    assert "Sanitization does" in _GRAPH_CRITIC_SYSTEM
    assert "not make retrieved text trusted" in _GRAPH_CRITIC_SYSTEM
    assert "items 17-27 are blocking" in _GRAPH_CRITIC_SYSTEM
    assert "Return exactly one topology proof" in _GRAPH_CRITIC_SYSTEM
    assert "Do not stop after finding the first defect" in _GRAPH_CRITIC_SYSTEM
    assert "event-stream systems define bounded" in _GRAPH_CRITIC_SYSTEM
    assert "backpressure and overload behavior" in _GRAPH_CRITIC_SYSTEM
    assert "partition/order or event-time semantics" in _GRAPH_CRITIC_SYSTEM
    assert "replay/checkpoint" in _GRAPH_CRITIC_SYSTEM
    assert "compatible schema evolution" in _GRAPH_CRITIC_SYSTEM


def test_required_topology_proofs_reject_missing_or_invented_edges():
    graph = {"edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]}
    value = [
        {
            "guarantee": guarantee,
            "status": "not_applicable",
            "edge_evidence": [],
            "reason": "This flow class is absent.",
        }
        for guarantee in (
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]
    value.append({
        "guarantee": "state_effect_reconciliation",
        "status": "pass",
        "edge_evidence": [{"source": "gate", "target": "writer", "label": "release action"}],
        "reason": "The action is supposedly reserved before execution.",
    })

    proofs, failures = _normalise_topology_proofs(value, graph=graph, required=True)

    assert len(proofs) == 5
    assert any("edge absent from the graph" in failure for failure in failures)


def test_required_topology_proofs_accept_exact_citations_from_semantic_reviewer():
    graph = {"edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]}
    value = [
        {
            "guarantee": guarantee,
            "status": "pass" if guarantee == "authorization_and_compensation" else "not_applicable",
            "edge_evidence": (
                [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "reason": "The cited path is present." if guarantee == "authorization_and_compensation" else "This flow class is absent.",
        }
        for guarantee in sorted({
            "state_effect_reconciliation",
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        })
    ]

    _, failures = _normalise_topology_proofs(value, graph=graph, required=True)

    assert failures == []


@pytest.mark.parametrize(
    ("guarantee", "label"),
    [
        ("state_effect_reconciliation", "Action Executor"),
        ("authorization_and_compensation", "Supervisor Approval"),
        ("retrieval_and_reuse_trust", "Scoped Answer Cache"),
        ("audit_and_provenance", "Lifecycle Audit Ledger"),
        ("learning_and_release", "Canary Release Gate"),
    ],
)
def test_topology_applicability_is_owned_by_semantic_review_not_label_regex(guarantee, label):
    graph = {
        "nodes": [{"id": "visible", "label": label}],
        "edges": [{"source": "visible", "target": "outcome", "label": "returns result"}],
    }
    value = [
        {
            "guarantee": item,
            "status": "not_applicable",
            "edge_evidence": [],
            "reason": "This flow class is absent.",
        }
        for item in (
            "state_effect_reconciliation",
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]

    _, failures = _normalise_topology_proofs(value, graph=graph, required=True)

    assert failures == []


def test_production_review_promotes_structural_advice_to_blocking_failure():
    review = _normalise_review(
        {
            "approved": True,
            "score": 0.9,
            "blocking_failures": [],
            "advice": [
                "Add an explicit rollback edge instead of leaving the transition in prose.",
                "Consider retaining metrics for seven more days.",
                "Could show an explicit ingestion edge, though it is reasonably scoped out.",
                "Consider adding an explicit optional audit edge for a secondary view.",
            ],
            "topology_proofs": [
                {
                    "guarantee": guarantee,
                    "status": "not_applicable",
                    "edge_evidence": [],
                    "reason": "This flow class is absent.",
                }
                for guarantee in (
                    "state_effect_reconciliation",
                    "authorization_and_compensation",
                    "retrieval_and_reuse_trust",
                    "audit_and_provenance",
                    "learning_and_release",
                )
            ],
        },
        graph={"edges": []},
        require_topology_proofs=True,
    )

    assert review["approved"] is False
    assert review["missing"] == [
        "Add an explicit rollback edge instead of leaving the transition in prose."
    ]
    assert review["advice"] == [
        "Consider retaining metrics for seven more days.",
        "Could show an explicit ingestion edge, though it is reasonably scoped out.",
        "Consider adding an explicit optional audit edge for a secondary view.",
    ]


def test_production_gate_accepts_cache_write_owned_by_acceptance_gate():
    graph = {
        "nodes": [
            {"id": "generator", "label": "Answer Generator"},
            {"id": "validator", "label": "Grounding Validator"},
            {"id": "fallback", "label": "No-Evidence Fallback"},
            {"id": "delivery", "label": "Response Delivery"},
            {"id": "cache", "label": "Answer Cache"},
        ],
        "edges": [
            {"source": "generator", "target": "validator", "label": "submit candidate"},
            {"source": "validator", "target": "cache", "label": "write accepted answer"},
            {"source": "validator", "target": "fallback", "label": "reject ungrounded answer"},
            {"source": "fallback", "target": "delivery", "label": "deliver abstention"},
            {"source": "cache", "target": "delivery", "label": "serve scoped answer"},
            {"source": "delivery", "target": "generator", "label": "return measured outcome", "flow": "feedback"},
        ],
    }

    review = _deterministic_review("Design a production RAG workflow", graph, "production")

    assert review["approved"] is True
    assert not any("cache writes" in item for item in review["missing"])


def test_production_gate_does_not_treat_approval_audit_store_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Permit Request", "type": "client"},
            # Even if the model classifies an audit projection as a control,
            # its ownership noun must keep it from becoming an approval gate.
            {"id": "ledger", "label": "Approval Audit Ledger", "type": "control"},
            {"id": "outcome", "label": "Permit Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "ledger", "label": "records reviewed permit"},
            {"source": "ledger", "target": "outcome", "label": "publishes audit projection"},
            {"source": "outcome", "target": "entry", "label": "returns measured outcome", "flow": "feedback"},
        ],
    }

    review = _deterministic_review("Design an audited permit workflow", graph, "production")

    assert not any("rejection/cancellation" in item for item in review["missing"])


def test_production_gate_does_not_treat_approved_registry_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Definition Proposal", "type": "service"},
            {
                "id": "registry",
                "label": "Event Definition Registry",
                "type": "control",
                "description": "Stores approved versioned definitions for canary release.",
            },
            {"id": "outcome", "label": "Definition Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "registry", "label": "register approved version"},
            {"source": "registry", "target": "outcome", "label": "publish immutable version"},
            {
                "source": "outcome",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design controlled event-definition releases",
        graph,
        "production",
    )

    assert not any("approval decision registry" in item for item in review["missing"])


def test_approval_owner_accepts_separate_approval_and_rejection_routes():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Audited Rejection", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {"source": "owner", "target": "lifecycle", "label": "approve exact action"},
            {"source": "owner", "target": "terminal", "label": "reject exact action"},
            {
                "source": "lifecycle",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
            {"source": "terminal", "target": "entry", "label": "return rejection outcome"},
        ],
    }

    review = _deterministic_review("Design a controlled external action", graph, "production")

    assert review["approved"] is True


def test_approval_owner_may_persist_both_outcomes_in_complete_durable_envelope():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Decision Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {
                "source": "owner",
                "target": "lifecycle",
                "label": "record approve or reject decision",
                "technology": "Signed payload and target envelope",
                "description": (
                    "Persists policy version, expiry, and idempotency key before any lease."
                ),
            },
            {"source": "lifecycle", "target": "terminal", "label": "publish decision outcome"},
        ],
    }

    review = _deterministic_review("Design a controlled clinical action", graph, "production")

    assert review["approved"] is True
    assert not any("approval decision" in item for item in review["missing"])
    assert not any("approval edge" in item for item in review["missing"])


def test_release_controller_may_own_promotion_and_rollback_for_registry_canary():
    graph = {
        "nodes": [
            {"id": "registry", "label": "Model Registry", "type": "datastore"},
            {"id": "controller", "label": "Rollout Controller", "type": "control"},
            {"id": "runtime", "label": "Decision Runtime", "type": "service"},
            {"id": "outcome", "label": "Canary Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "registry", "target": "controller", "label": "supplies immutable release"},
            {"source": "controller", "target": "runtime", "label": "deploy canary"},
            {"source": "controller", "target": "runtime", "label": "promote full production"},
            {"source": "controller", "target": "registry", "label": "rollback to prior release"},
            {"source": "runtime", "target": "outcome", "label": "measure canary"},
            {"source": "outcome", "target": "controller", "label": "returns measured outcome", "flow": "feedback"},
        ],
    }

    review = _deterministic_review("Design a controlled model release", graph, "production")

    assert review["approved"] is True
    assert not any("canary" in item.lower() for item in review["missing"])


def test_reservation_store_description_does_not_make_it_an_executor():
    graph = {
        "nodes": [
            {"id": "policy", "label": "Risk Policy", "type": "decision"},
            {
                "id": "reservation",
                "label": "Operation Reservation",
                "type": "datastore",
                "description": "Owns durable execution lifecycle state and leases.",
            },
            {"id": "executor", "label": "Channel Executor", "type": "gateway"},
            {"id": "outcome", "label": "Campaign Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "policy",
                "target": "reservation",
                "label": "forward auto-authorized payload",
                "technology": "Signed target envelope",
                "description": "Binds policy version, expiry, and idempotency key.",
            },
            {"source": "reservation", "target": "executor", "label": "lease reserved operation"},
            {"source": "executor", "target": "outcome", "label": "execute campaign change"},
            {"source": "outcome", "target": "policy", "label": "return measured outcome", "flow": "feedback"},
        ],
    }

    review = _deterministic_review("Design an automatic campaign workflow", graph, "production")

    assert review["approved"] is True
    assert not any("durable reservation state" in item for item in review["missing"])


def test_read_only_external_adapter_is_not_treated_as_effect_executor():
    graph = {
        "nodes": [
            {"id": "reservation", "label": "Query Lifecycle", "type": "datastore"},
            {"id": "adapter", "label": "Ad Platform Adapter", "type": "gateway"},
            {"id": "target", "label": "Ad Platform", "type": "external"},
            {"id": "reconciler", "label": "Query Reconciler", "type": "service"},
        ],
        "edges": [
            {"source": "reservation", "target": "adapter", "label": "lease reserved query"},
            {"source": "adapter", "target": "target", "label": "query campaign status"},
            {"source": "target", "target": "reconciler", "label": "return campaign status"},
            {"source": "reconciler", "target": "adapter", "label": "NOT_FOUND retry read"},
            {
                "source": "reconciler",
                "target": "reservation",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review("Design a read-only campaign status lookup", graph, "production")

    assert review["approved"] is True
    assert not any("durable reservation" in item for item in review["missing"])


def test_distinct_reconciliation_branch_may_contrast_other_outcomes_and_share_audit():
    graph = {
        "nodes": [
            {"id": "ledger", "label": "Lifecycle Ledger", "type": "datastore"},
            {"id": "adapter", "label": "Fulfilment Adapter", "type": "gateway"},
            {"id": "target", "label": "External Fulfilment", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "control"},
            {"id": "audit", "label": "Audit Log", "type": "datastore"},
        ],
        "edges": [
            {"source": "ledger", "target": "adapter", "label": "lease reserved operation"},
            {"source": "adapter", "target": "target", "label": "apply fulfilment mutation"},
            {"source": "target", "target": "reconciler", "label": "return status"},
            {
                "source": "reconciler",
                "target": "ledger",
                "label": "NOT_FOUND retry reservation",
                "description": "Retries only NOT_FOUND; STILL_UNKNOWN escalates on its own branch.",
            },
            {
                "source": "reconciler",
                "target": "audit",
                "label": "log reconciliation outcomes",
                "description": "Audits COMMITTED, NOT_FOUND, and STILL_UNKNOWN branch results.",
            },
        ],
    }

    review = _deterministic_review("Design a fulfilment integration", graph, "production")

    assert not any("distinct reconciliation branches" in item for item in review["missing"])


def test_domain_specific_connected_topology_passes_local_structural_checks():
    graph = {
        "nodes": [
            {"id": "report", "label": "Missing Bag Report"},
            {"id": "router", "label": "Recovery Route Decision"},
            {"id": "resolution", "label": "Passenger Resolution"},
        ],
        "edges": [
            {"source": "report", "target": "router", "label": "submits verified bag record"},
            {"source": "router", "target": "resolution", "label": "returns recovery outcome"},
        ],
    }

    review = _deterministic_review(
        "Design an airport baggage recovery workflow",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def _domain_graph():
    return {
        "design_origin": "applied",
        "nodes": [
            {"label": "Campaign Objective", "description": "Defines ROAS objective and spend constraints"},
            {"label": "Event Quality Gate", "description": "Validates conversion and attribution events"},
            {"label": "Creative Optimizer", "description": "Chooses copy variants for an audience"},
            {"label": "Approval Policy", "description": "Approves risky actions and writes an audit record"},
            {"label": "Channel Executor", "description": "Applies idempotent targeting and bid changes"},
            {"label": "Outcome Attribution", "description": "Observes attributed revenue and campaign outcomes"},
        ],
        "edges": [
            {
                "source": "outcome",
                "target": "objective",
                "label": "returns attributed outcomes",
                "description": "Closes the measured optimization loop",
                "type": "loop",
            }
        ],
    }


def test_deterministic_review_accepts_a_domain_control_loop():
    review = _deterministic_review(
        "Design a growth marketing agent that optimizes campaign attribution",
        _domain_graph(),
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["score"] >= 0.78


@pytest.mark.parametrize(
    ("query", "labels"),
    [
        (
            "Design a municipal water-leak triage system",
            ("Leak Report", "Dispatch Decision", "Repair Outcome"),
        ),
        (
            "Design a telescope transient-alert pipeline",
            ("Sky Event", "Candidate Classifier", "Observer Outcome"),
        ),
        (
            "Design a music-royalty reconciliation service",
            ("Usage Evidence", "Royalty Reconciler", "Dispute Outcome"),
        ),
        (
            "Design an airport baggage recovery workflow",
            ("Missing Bag", "Recovery Router", "Passenger Outcome"),
        ),
    ],
)
def test_feedback_flow_is_a_loop_without_renderer_specific_metadata(query, labels):
    graph = {
        "design_origin": "applied",
        "nodes": [
            {"id": "entry", "label": labels[0], "description": "Captures a verified request."},
            {"id": "decision", "label": labels[1], "description": "Owns the bounded decision."},
            {"id": "outcome", "label": labels[2], "description": "Records the measured outcome."},
        ],
        "edges": [
            {"source": "entry", "target": "decision", "label": "sends verified input"},
            {"source": "decision", "target": "outcome", "label": "records bounded result"},
            {
                "source": "outcome",
                "target": "decision",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(query, graph, "prototype")

    assert review["approved"] is True
    assert review["missing"] == []


def test_deterministic_gate_does_not_guess_semantics_from_prose_vocabulary():
    graph = _domain_graph()
    graph["nodes"][-1] = {
        "label": "Outcome Evaluator",
        "description": "Computes campaign performance metrics for the feedback loop",
    }

    review = _deterministic_review(
        "Design a production growth marketing agent for campaign performance",
        graph,
        "production",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def test_generic_book_vocabulary_is_rejected_before_publication():
    graph = {
        "nodes": [
            {"label": label, "description": "Generic book concept"}
            for label in (
                "Agent", "Tool Use", "Planning", "Evaluation", "Foundation Model", "Generation"
            )
        ],
        "edges": [{
            "source": "agent",
            "target": "planning",
            "label": "returns measured outcome",
            "type": "loop",
        }],
    }

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_one_standalone_generic_label_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"][0] = {"label": "Agent", "description": "Owns the campaign objective"}

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_disconnected_architecture_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"] = [
        {**node, "id": f"node_{index}"}
        for index, node in enumerate(graph["nodes"])
    ]

    review = _deterministic_review(
        "Design a growth marketing optimization system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("Connect every component" in item for item in review["missing"])


def test_read_only_design_does_not_invent_an_external_write_boundary():
    graph = {
        "nodes": [
            {"id": "request", "label": "Research Request", "description": "Captures the research question"},
            {"id": "retriever", "label": "Evidence Retriever", "description": "Retrieves cited source passages"},
            {"id": "composer", "label": "Answer Composer", "description": "Builds a grounded answer"},
        ],
        "edges": [
            {
                "source": "request",
                "target": "retriever",
                "label": "submits ACL-scoped query",
            },
            {
                "source": "retriever",
                "target": "composer",
                "label": "returns cited passages",
            },
        ],
    }

    review = _deterministic_review(
        "Design a research assistant system",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert not any("approval" in item for item in review["missing"])
    assert not any("feedback" in item for item in review["missing"])


def test_explicit_optimisation_request_requires_a_measured_feedback_edge():
    graph = {
        "nodes": [
            {"id": "input", "label": "Observed Outcome"},
            {"id": "decision", "label": "Allocation Decision"},
            {"id": "result", "label": "Allocation Result"},
        ],
        "edges": [
            {"source": "input", "target": "decision", "label": "supplies measured evidence"},
            {"source": "decision", "target": "result", "label": "returns bounded allocation"},
        ],
    }

    review = _deterministic_review(
        "Design a system that continuously optimizes allocations from measured outcomes",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("feedback edge" in item for item in review["missing"])


def test_model_cannot_override_a_failed_local_quality_gate():
    local = {"approved": False, "score": 0.7, "missing": ["Missing approval"], "strengths": []}
    model = _normalise_review({"approved": True, "score": 0.95, "missing": [], "strengths": ["Looks good"]})

    merged = _merge_reviews(local, model)

    assert merged["approved"] is False
    assert merged["score"] == 0.7
    assert merged["missing"] == ["Missing approval"]


def test_review_requires_a_json_boolean_and_string_lists():
    review = _normalise_review({
        "approved": "false",
        "score": 0.99,
        "missing": [{"not": "a string"}],
        "strengths": ["Specific", 123],
    })

    assert review["approved"] is False
    assert review["missing"] == []
    assert review["strengths"] == ["Specific"]


def test_optional_model_advice_does_not_block_a_publishable_diagram():
    local = {"approved": True, "score": 0.92, "missing": [], "strengths": ["Safe boundary"]}
    model = _normalise_review({
        "approved": True,
        "score": 0.84,
        "blocking_failures": [],
        "advice": ["Consider a secondary on-call route."],
        "strengths": ["Domain specific"],
    })

    merged = _merge_reviews(local, model)

    assert merged["approved"] is True
    assert merged["missing"] == []
    assert merged["advice"] == ["Consider a secondary on-call route."]


def test_explicit_model_blocking_failure_still_rejects_the_diagram():
    review = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": ["The requested rollback path is absent."],
        "advice": [],
    })

    assert review["approved"] is False
    assert review["missing"] == ["The requested rollback path is absent."]


def test_prototype_review_preserves_semantic_reviewer_rejection():
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [
                "Replace the narrated outcome edge with explicit COMMITTED, NOT_FOUND, and STILL_UNKNOWN branches."
            ],
            "revision_instruction": "Draw all three reconciliation branches.",
        },
    )

    assert review["approved"] is False
    assert len(review["missing"]) == 1
    assert review["revision_instruction"] == "Draw all three reconciliation branches."


def test_selected_prototype_depth_does_not_reverse_semantic_rejection():
    failure = "Split COMMITTED, NOT_FOUND, and STILL_UNKNOWN into distinct branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_explicit_reconciliation_request_remains_blocking_at_prototype_depth():
    failure = "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_prototype_review_keeps_approval_envelope_rejection():
    failure = (
        "Give every approval decision distinct approval and rejection routes, or persist "
        "both outcomes in one complete exact-action envelope at durable lifecycle state."
    )
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.72,
            "blocking_failures": [failure],
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_explicit_approval_boundary_request_remains_blocking_at_prototype_depth():
    failure = "Give every approval decision distinct approval and rejection routes."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.72,
            "blocking_failures": [failure],
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_semantic_review_preserves_all_independent_prototype_blockers():
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.65,
            "blocking_failures": [
                "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches.",
                "The memory store has no directed read path back to the agent.",
            ],
            "revision_instruction": "Repair both paths.",
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [
        "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches.",
        "The memory store has no directed read path back to the agent.",
    ]
    assert review["revision_instruction"] == "Repair both paths."
    assert review["advice"] == []


def test_production_reconciliation_failure_is_never_depth_scoped_away():
    failure = "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_render_gate_rejects_overlap_clipping_or_missing_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 0,
            "overlap_count": 1,
            "clipped_nodes": 1,
            "clipped_edges": 1,
            "minimum_text_px": 8,
        },
    })

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("actual candidate" in item for item in review["missing"])
    assert any("overlapping" in item for item in review["missing"])


def test_render_gate_accepts_a_complete_readable_browser_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "valid-bounded-image",
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
        },
    })

    assert review["approved"] is True
    assert review["terminal"] is False


def test_render_gate_rejects_missing_overview_and_group_labels_or_overlapping_zones():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "valid-bounded-image",
        "report": {
            "rendered_nodes": 2,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
            "overview_required_edge_labels": 1,
            "visible_overview_required_edge_labels": 0,
            "grouped_nodes": 2,
            "group_labelled_nodes": 1,
            "visible_group_boundaries": 2,
            "group_boundary_overlap_count": 1,
        },
    })

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("overview-required edge label" in item for item in review["missing"])
    assert any("group label on every node" in item for item in review["missing"])
    assert any("responsibility-zone boundaries" in item for item in review["missing"])


def test_render_gate_accepts_legacy_reports_without_new_visual_metrics():
    graph = {"nodes": [{"id": "a"}], "edges": []}
    review = _deterministic_render_review(graph, {
        "screenshot_base64": "legacy-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 7,
        },
    })

    assert review["approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_count", "expected_effort"),
    [(0, "high"), (1, "high")],
)
async def test_semantic_critic_reviews_the_private_rendered_image(
    monkeypatch,
    revision_count,
    expected_effort,
):
    captured = {}
    architect_tail = "a" * 10_100 + " architect-tail"
    challenger_tail = "c" * 6_100 + " challenger-tail"

    async def fake_stream_llm(**kwargs):
        captured.update(kwargs)
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["Domain responsibilities are explicit."],
            "blocking_failures": [],
            "advice": [],
            "topology_proofs": [
                {
                    "guarantee": guarantee,
                    "status": "not_applicable",
                    "edge_evidence": [],
                    "reason": "This isolated transport test does not exercise the flow class.",
                }
                for guarantee in (
                    "state_effect_reconciliation",
                    "authorization_and_compensation",
                    "retrieval_and_reuse_trust",
                    "audit_and_provenance",
                    "learning_and_release",
                )
            ],
            "revision_instruction": "",
        })

    async def send(_event):
        return None

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render-image",
            "media_type": "image/png",
            "report": {
                "rendered_nodes": 6,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    result = await graph_critic_node({
        "graph_data": graph,
        "graph_changed": True,
        "user_message": "Design a production growth marketing agent system",
        "evidence_bundle": {
            "checklist": [{"area": "evaluation", "question": "Measure outcomes"}],
            "book_evidence": [{"chapter": 1, "page_number": 8, "text": "Evaluate measured outcomes."}],
            "research_context": "- [Current source](https://example.com): current evidence",
        },
        "architect_plan": {
            "diagram_requirements": [architect_tail],
        },
        "challenger_review": {
            "risks": [
                {"area": "safety", "risk": "Unapproved writes", "mitigation": "Approval gate"},
                {"area": "completeness", "risk": challenger_tail, "mitigation": "Keep it visible"},
            ],
        },
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
        "graph_revision_count": revision_count,
    })

    assert result["graph_review"]["approved"] is True
    assert captured["effort"] == expected_effort
    content = captured["messages"][0]["content"]
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "private-render-image",
        },
    }
    review_text = content[0]["text"]
    assert "Browser layout report" in review_text
    assert "Supplied evidence allowlist" in review_text
    assert "https://example.com" in review_text
    assert "Independent challenger findings" in review_text
    assert "Unapproved writes" in review_text
    assert "architect-tail" in review_text
    assert "challenger-tail" in review_text
    assert "Judge its visual hierarchy" in _GRAPH_CRITIC_SYSTEM


@pytest.mark.asyncio
async def test_terse_followup_still_reviews_every_changed_applied_graph(monkeypatch):
    calls = {"critic": 0, "render": 0}

    async def fake_stream_llm(**_kwargs):
        calls["critic"] += 1
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The requested approval path remains domain specific."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def await_diagram(graph):
        calls["render"] += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "expand the approval path",
        "design_query": "growth marketing multi-agent system expand the approval path",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert calls == {"critic": 1, "render": 1}


@pytest.mark.asyncio
async def test_hard_render_failure_skips_the_paid_semantic_critic(monkeypatch):
    async def fail_stream_llm(**_kwargs):
        raise AssertionError("hard deterministic failures must not spend a critic call")

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": 5,
                "rendered_edges": 1,
                "overlap_count": 1,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fail_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is False
    assert any("overlapping" in item for item in result["graph_review"]["missing"])
    assert result["graph_review"].get("terminal") is not True


@pytest.mark.asyncio
async def test_missing_browser_evaluation_fails_closed_before_paid_semantic_review(
    monkeypatch,
):
    calls = 0

    async def fake_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def await_diagram(_graph):
        raise TimeoutError("browser did not respond")

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    graph = _domain_graph()
    result = await graph_critic_node({
        "graph_data": graph,
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert calls == 0
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "diagram_evaluation_timeout"


@pytest.mark.asyncio
async def test_render_fallback_never_overrides_deterministic_domain_failure(monkeypatch, caplog):
    async def fail_stream_llm(**_kwargs):
        raise AssertionError("deterministic rejection must skip semantic review")

    async def fail_await_diagram(_graph):
        raise AssertionError("deterministic rejection must skip browser evaluation")

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fail_stream_llm)
    graph = _domain_graph()
    graph["nodes"][0]["label"] = "Agent"
    result = await graph_critic_node({
        "graph_data": graph,
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": fail_await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is False
    assert "diagram_evaluation_fallback_admit" not in caplog.text


@pytest.mark.asyncio
async def test_malformed_semantic_review_retries_once_then_accepts(monkeypatch):
    calls = []
    render_calls = 0
    responses = iter([
        '{"approved": tru',
        json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        }),
    ])

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return next(responses)

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 2
    assert all(call["model"] == settings.graph_qa_model for call in calls)
    assert all(call["timeout_seconds"] <= settings.graph_critic_initial_timeout_s for call in calls)
    assert all(
        call["max_output_tokens"]
        == settings.graph_qa_max_completion_tokens
        for call in calls
    )
    assert all(call["thinking_budget"] is None for call in calls)
    assert all(call["effort"] == "high" for call in calls)
    assert render_calls == 1
    assert [call["telemetry"]["metadata"]["semantic_attempt"] for call in calls] == [0, 1]
    assert calls[1]["effort"] == "high"
    retry_text = calls[1]["messages"][0]["content"][0]["text"]
    assert "Protocol failure: ValueError" in retry_text
    assert "Prior response:" in retry_text


@pytest.mark.asyncio
async def test_browser_render_time_is_deducted_from_one_absolute_critic_deadline(
    monkeypatch,
):
    clock = {"now": 100.0}
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def await_diagram(graph):
        clock["now"] += 7.0
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(event):
        events.append(event)

    monkeypatch.setattr("agent.nodes.graph_critic.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
        "_graph_stage_deadline_s": 145.0,
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert calls[0]["timeout_seconds"] == pytest.approx(37.0)
    assert any(
        event.get("phase") == "review" and event.get("status") == "complete"
        for event in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "approved": "true",
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        },
        {
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        },
    ],
)
async def test_invalid_semantic_review_contract_retries_then_accepts(
    monkeypatch,
    invalid_payload,
):
    calls = []
    render_calls = 0
    responses = iter([
        json.dumps(invalid_payload),
        json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        }),
    ])

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return next(responses)

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 2
    assert render_calls == 1
    assert (
        "critic response protocol invalid"
        in calls[1]["messages"][0]["content"][0]["text"]
    )


def _valid_protocol_topology_proofs(edge=None):
    edge = edge or {
        "source": "source_node",
        "target": "target_node",
        "label": "carries typed payload",
    }
    return [
        {
            "guarantee": guarantee,
            "status": "pass",
            "edge_evidence": [edge],
            "reason": "The cited directed edge proves this guarantee.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]


def _protocol_review(topology_proofs):
    return {
        "approved": True,
        "score": 0.9,
        "strengths": ["The runtime path is explicit."],
        "blocking_failures": [],
        "advice": [],
        "topology_proofs": topology_proofs,
        "revision_instruction": "",
    }


@pytest.mark.parametrize(
    "defect",
    [
        "missing_proof",
        "duplicate_guarantee",
        "invalid_status",
        "invalid_evidence",
        "empty_pass_evidence",
        "invalid_reason",
    ],
)
def test_production_critic_protocol_rejects_malformed_topology_proofs(defect):
    proofs = _valid_protocol_topology_proofs()
    if defect == "missing_proof":
        proofs.pop()
    elif defect == "duplicate_guarantee":
        proofs[-1]["guarantee"] = proofs[0]["guarantee"]
    elif defect == "invalid_status":
        proofs[0]["status"] = "approved"
    elif defect == "invalid_evidence":
        proofs[0]["edge_evidence"] = [{"source": "source_node"}]
    elif defect == "empty_pass_evidence":
        proofs[0]["edge_evidence"] = []
    else:
        proofs[0]["reason"] = ["not", "a", "string"]

    with pytest.raises(ValueError, match="critic response protocol invalid"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
        )


def test_production_critic_protocol_accepts_complete_topology_proofs():
    _validate_review_protocol(
        _protocol_review(_valid_protocol_topology_proofs()),
        require_topology_proofs=True,
    )


@pytest.mark.asyncio
async def test_malformed_topology_proofs_retry_as_protocol_defect(monkeypatch):
    graph = _domain_graph()
    edge = graph["edges"][0]
    evidence_edge = {
        "source": edge["source"],
        "target": edge["target"],
        "label": edge["label"],
    }
    malformed = _valid_protocol_topology_proofs(evidence_edge)
    malformed[-1]["guarantee"] = malformed[0]["guarantee"]
    responses = iter([
        json.dumps(_protocol_review(malformed)),
        json.dumps(_protocol_review(_valid_protocol_topology_proofs(evidence_edge))),
    ])
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return next(responses)

    async def await_diagram(candidate):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(candidate["nodes"]),
                "rendered_edges": len(candidate["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    monkeypatch.setattr(
        "agent.nodes.graph_critic._deterministic_review",
        lambda *_args, **_kwargs: {
            "approved": True,
            "score": 1.0,
            "strengths": [],
            "missing": [],
            "advice": [],
            "revision_instruction": "",
        },
    )
    result = await graph_critic_node({
        "graph_data": graph,
        "graph_changed": True,
        "user_message": "production growth marketing multi-agent system",
        "complexity": "production",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 2
    assert "topology_proofs" in calls[1]["messages"][0]["content"][0]["text"]


@pytest.mark.asyncio
async def test_protocol_retry_skips_when_remaining_budget_is_insufficient(monkeypatch):
    calls = 0

    async def fake_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        return '{"approved": tru'

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    monkeypatch.setattr(
        "agent.nodes.graph_critic._remaining_protocol_retry_seconds",
        lambda _deadline: _GRAPH_CRITIC_PROTOCOL_RETRY_MIN_REMAINING_S - 0.001,
    )
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert calls == 1
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert any(
        "semantic architecture review did not complete" in item
        for item in result["graph_review"]["missing"]
    )


@pytest.mark.asyncio
async def test_protocol_retry_runs_at_minimum_remaining_budget(monkeypatch):
    calls = []
    responses = iter([
        '{"approved": tru',
        json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        }),
    ])

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return next(responses)

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    monkeypatch.setattr(
        "agent.nodes.graph_critic._remaining_protocol_retry_seconds",
        lambda _deadline: _GRAPH_CRITIC_PROTOCOL_RETRY_MIN_REMAINING_S,
    )
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_malformed_semantic_review_twice_fails_closed(monkeypatch):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return '{"approved": tru'

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert len(calls) == 2
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert any(
        "semantic architecture review did not complete" in item
        for item in result["graph_review"]["missing"]
    )


@pytest.mark.asyncio
async def test_valid_first_semantic_review_uses_one_call(monkeypatch):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return json.dumps({
            "approved": True,
            "score": 0.9,
            "strengths": ["The runtime path is explicit."],
            "blocking_failures": [],
            "advice": [],
            "revision_instruction": "",
        })

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fake_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert calls[0]["telemetry"]["metadata"]["semantic_attempt"] == 0


def test_compact_semantic_review_preserves_complete_blockers():
    from agent.nodes.graph_critic import _compact_review_payload

    payload = _compact_review_payload({
        "approved": False,
        "strengths": ["a" * 200, "second", "discarded"],
        "missing": ["first", "second", "x" * 500],
        "advice": ["a", "b", "discarded"],
        "revision_instruction": "r" * 600,
        "topology_proofs": {"approval": "preserved"},
    })

    assert len(payload["strengths"]) == 2
    assert len(payload["strengths"][0]) == 160
    assert payload["missing"] == ["first", "second", "x" * 500]
    assert payload["advice"] == ["a", "b"]
    assert len(payload["revision_instruction"]) == 440
    assert payload["topology_proofs"] == {"approval": "preserved"}


def test_semantic_review_failure_classifies_truncated_protocol_output():
    from agent.nodes.graph_critic import _semantic_review_failure_code

    assert _semantic_review_failure_code(
        ValueError("invalid JSON"),
        '{"approved":false',
    ) == "semantic_review_output_truncated"
    assert _semantic_review_failure_code(
        TimeoutError("provider unavailable"),
        "",
    ) == "semantic_review_timeout"


@pytest.mark.asyncio
async def test_semantic_critic_outage_fails_closed(monkeypatch):
    calls = 0
    events = []

    async def fail_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider unavailable")

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 8,
            },
        }

    async def send(event):
        events.append(event)

    monkeypatch.setattr("agent.nodes.graph_critic.stream_llm", fail_stream_llm)
    result = await graph_critic_node({
        "graph_data": _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": "prototype",
        "send": send,
        "await_diagram_evaluation": await_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    })

    assert calls == 1
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_timeout"
    assert any(
        event.get("failure_code") == "semantic_review_timeout" for event in events
    )
    assert any(
        "semantic architecture review did not complete" in item
        for item in result["graph_review"]["missing"]
    )
