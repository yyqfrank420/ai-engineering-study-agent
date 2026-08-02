import json

import pytest

from agent.nodes.graph_critic import (
    _GRAPH_CRITIC_PROMPT_VERSION,
    _GRAPH_CRITIC_SYSTEM,
    _critic_thinking_budget,
    _deterministic_render_review,
    _deterministic_review,
    _merge_reviews,
    _normalise_review,
    _normalise_topology_proofs,
    _reconcile_objective_render_claims,
    graph_critic_node,
)


def test_revision_critic_uses_bounded_verification_budget():
    assert _critic_thinking_budget(9000, 0) == 2000
    assert _critic_thinking_budget(9000, 1) == 1200
    assert _critic_thinking_budget(None, 1) is None


def test_semantic_critic_rejects_cache_replay_or_retry_gate_bypasses():
    assert _GRAPH_CRITIC_PROMPT_VERSION == "architecture_critic_v19"
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
def test_topology_proof_cannot_claim_not_applicable_for_visible_flow(guarantee, label):
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

    assert any(guarantee.replace("_", " ") in failure for failure in failures)


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


@pytest.mark.parametrize(
    ("nodes", "edges", "expected"),
    [
        (
            [
                {"id": "request", "label": "Permit Request"},
                {"id": "approval", "label": "Officer Approval", "type": "decision", "description": "Approves or rejects the exact permit."},
                {"id": "writer", "label": "Permit Writer"},
            ],
            [
                {"source": "request", "target": "approval", "label": "submit proposal"},
                {"source": "approval", "target": "writer", "label": "approve permit"},
                {"source": "writer", "target": "request", "label": "return measured outcome", "flow": "feedback"},
            ],
            "approval decision",
        ),
        (
            [
                {"id": "gate", "label": "Evidence Gate"},
                {"id": "fallback", "label": "Fallback"},
                {"id": "delivery", "label": "Response Delivery"},
                {"id": "cache", "label": "Answer Cache"},
            ],
            [
                {"source": "gate", "target": "fallback", "label": "no-evidence fallback"},
                {"source": "fallback", "target": "delivery", "label": "deliver fallback"},
                {"source": "delivery", "target": "cache", "label": "write accepted answer"},
                {"source": "cache", "target": "gate", "label": "return measured outcome", "flow": "feedback"},
            ],
            "Separate accepted-artifact cache writes",
        ),
        (
            [
                {"id": "writer", "label": "Command Writer"},
                {"id": "reconciler", "label": "Outcome Reconciler"},
                {"id": "ledger", "label": "Lifecycle Ledger"},
            ],
            [
                {"source": "writer", "target": "reconciler", "label": "timeout"},
                {"source": "reconciler", "target": "ledger", "label": "write COMMITTED/NOT_FOUND/STILL_UNKNOWN"},
                {"source": "ledger", "target": "writer", "label": "return measured outcome", "flow": "feedback"},
            ],
            "distinct reconciliation branches",
        ),
        (
            [
                {"id": "policy", "label": "Risk Policy"},
                {"id": "executor", "label": "Action Executor"},
                {"id": "outcome", "label": "Action Outcome"},
            ],
            [
                {"source": "policy", "target": "executor", "label": "auto-approve low-risk action"},
                {"source": "executor", "target": "outcome", "label": "execute action"},
                {"source": "outcome", "target": "policy", "label": "return measured outcome", "flow": "feedback"},
            ],
            "automatic-action authorization envelope",
        ),
        (
            [
                {"id": "registry", "label": "Model Registry"},
                {"id": "runtime", "label": "Decision Runtime"},
                {"id": "outcome", "label": "Canary Outcome"},
            ],
            [
                {"source": "registry", "target": "runtime", "label": "deploy canary"},
                {"source": "runtime", "target": "outcome", "label": "measure canary"},
                {"source": "outcome", "target": "registry", "label": "return measured outcome", "flow": "feedback"},
            ],
            "canary promotion to full production",
        ),
        (
            [
                {"id": "approval", "label": "Supervisor Approval", "type": "decision"},
                {"id": "ledger", "label": "Action Ledger"},
                {"id": "sender", "label": "Action Sender"},
                {"id": "target", "label": "External Target"},
            ],
            [
                {"source": "approval", "target": "sender", "label": "forward approved action", "description": "Carries payload, target, policy version, expiry, and idempotency key."},
                {"source": "approval", "target": "ledger", "label": "reject to audited state"},
                {"source": "ledger", "target": "sender", "label": "provide reserved lease"},
                {"source": "sender", "target": "target", "label": "execute external action"},
                {"source": "target", "target": "approval", "label": "return measured outcome", "flow": "feedback"},
            ],
            "into durable reservation state",
        ),
    ],
)
def test_production_gate_rejects_label_only_control_topology(nodes, edges, expected):
    review = _deterministic_review(
        "Design an unrelated production workflow",
        {"nodes": nodes, "edges": edges},
        "production",
    )

    assert review["approved"] is False
    assert any(expected in item for item in review["missing"])


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


@pytest.mark.parametrize(
    ("owner_type", "owner_label", "owner_description"),
    [
        ("decision", "Clinician Sign-off", "Authorizes or denies the exact prescription."),
        ("control", "Campaign Approver", "Owns the human action decision."),
    ],
)
def test_approval_owner_requires_distinct_approval_and_rejection_routes(
    owner_type,
    owner_label,
    owner_description,
):
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {
                "id": "owner",
                "label": owner_label,
                "type": owner_type,
                "description": owner_description,
            },
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "outcome", "label": "Action Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {
                "source": "owner",
                "target": "lifecycle",
                "label": "approve or reject exact action",
            },
            {"source": "lifecycle", "target": "outcome", "label": "record decision"},
            {
                "source": "outcome",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review("Design a controlled external action", graph, "production")

    assert review["approved"] is False
    assert any("approval decision" in item for item in review["missing"])


def test_review_reports_every_incomplete_approval_owner_with_its_node_id():
    graph = {
        "nodes": [
            {"id": "proposal", "label": "Campaign Proposal", "type": "service"},
            {"id": "policy_gate", "label": "Policy Approval", "type": "control"},
            {"id": "human_gate", "label": "Human Approval", "type": "decision"},
            {"id": "outcome", "label": "Campaign Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "proposal", "target": "policy_gate", "label": "submit action"},
            {
                "source": "policy_gate",
                "target": "human_gate",
                "label": "approve or reject policy decision",
            },
            {
                "source": "human_gate",
                "target": "outcome",
                "label": "approve or reject campaign decision",
            },
            {
                "source": "outcome",
                "target": "proposal",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review("Design a controlled campaign system", graph, "production")

    approval_failures = [
        item for item in review["missing"] if "approval decision" in item
    ]
    assert len(approval_failures) == 2
    assert any("policy_gate" in item for item in approval_failures)
    assert any("human_gate" in item for item in approval_failures)


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


def test_canary_deploy_and_promotion_prose_do_not_fake_full_promotion_edge():
    graph = {
        "nodes": [
            {"id": "eval", "label": "Offline Evaluation", "type": "control"},
            {"id": "registry", "label": "Model Registry", "type": "datastore"},
            {"id": "runtime", "label": "Decision Runtime", "type": "service"},
            {"id": "outcome", "label": "Canary Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "eval", "target": "registry", "label": "offline eval before promotion"},
            {"source": "registry", "target": "runtime", "label": "promote canary version"},
            {"source": "runtime", "target": "outcome", "label": "measure canary"},
            {"source": "outcome", "target": "registry", "label": "pull promoted version"},
            {"source": "outcome", "target": "eval", "label": "return measured outcome", "flow": "feedback"},
        ],
    }

    review = _deterministic_review("Design a controlled model release", graph, "production")

    assert review["approved"] is False
    assert any("promotion to full production" in item for item in review["missing"])


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


def test_compensation_cannot_bypass_reservation_into_executor():
    graph = {
        "nodes": [
            {"id": "reservation", "label": "Operation Reservation", "type": "datastore"},
            {"id": "executor", "label": "Channel Executor", "type": "gateway"},
            {"id": "target", "label": "Ad Platform", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "service"},
        ],
        "edges": [
            {"source": "reservation", "target": "executor", "label": "lease reserved operation"},
            {"source": "executor", "target": "target", "label": "execute campaign change"},
            {"source": "target", "target": "reconciler", "label": "return authoritative status"},
            {
                "source": "reconciler",
                "target": "executor",
                "label": "trigger revert via same approval path",
            },
            {
                "source": "reconciler",
                "target": "reservation",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review("Design a compensated campaign workflow", graph, "production")

    assert review["approved"] is False
    assert any(
        "reconciler -> executor" in item and "compensating actions" in item
        for item in review["missing"]
    )


@pytest.mark.parametrize(
    "bypass_label",
    [
        "NOT_FOUND retry with the same idempotency key",
        "forward approved campaign mutation",
        "submit compensating campaign mutation",
    ],
)
def test_external_mutation_adapter_cannot_bypass_reservation(bypass_label):
    graph = {
        "nodes": [
            {"id": "reservation", "label": "Action Reservation", "type": "datastore"},
            {"id": "adapter", "label": "Ad Platform Adapter", "type": "gateway"},
            {"id": "target", "label": "Ad Platform", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "service"},
        ],
        "edges": [
            {"source": "reservation", "target": "adapter", "label": "lease reserved action"},
            {
                "source": "adapter",
                "target": "target",
                "label": "publishes campaign mutation",
            },
            {"source": "target", "target": "reconciler", "label": "return authoritative status"},
            {"source": "reconciler", "target": "adapter", "label": bypass_label},
            {
                "source": "reconciler",
                "target": "reservation",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review("Design a production campaign writer", graph, "production")

    assert review["approved"] is False
    assert any(
        "reconciler -> adapter" in item and "durable reservation" in item
        for item in review["missing"]
    )


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


def test_critic_reports_all_repairable_control_defects_together():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Proposal", "type": "service"},
            {"id": "approval", "label": "Clinical Sign-off", "type": "control"},
            {"id": "ledger", "label": "Lifecycle Ledger", "type": "datastore"},
            {"id": "adapter", "label": "Fulfilment Adapter", "type": "gateway"},
            {"id": "target", "label": "External Fulfilment", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "control"},
            {"id": "registry", "label": "Release Registry", "type": "datastore"},
        ],
        "edges": [
            {"source": "entry", "target": "approval", "label": "submit proposal"},
            {"source": "approval", "target": "ledger", "label": "approve or reject action"},
            {"source": "ledger", "target": "adapter", "label": "lease reserved operation"},
            {"source": "adapter", "target": "target", "label": "apply fulfilment mutation"},
            {"source": "target", "target": "reconciler", "label": "return status"},
            {"source": "reconciler", "target": "adapter", "label": "NOT_FOUND retry"},
            {
                "source": "reconciler",
                "target": "ledger",
                "label": "reconcile status",
                "description": "Returns COMMITTED, NOT_FOUND, or STILL_UNKNOWN together.",
            },
            {
                "source": "registry",
                "target": "adapter",
                "label": "deploy release",
                "technology": "Canary/promoted deployment",
            },
        ],
    }

    review = _deterministic_review("Design an optimized fulfilment system", graph, "production")

    assert review["approved"] is False
    assert any("approval decision" in item for item in review["missing"])
    assert any("durable reservation" in item for item in review["missing"])
    assert any("distinct reconciliation branches" in item for item in review["missing"])
    assert any("canary deployment" in item for item in review["missing"])


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


def test_prototype_review_downgrades_only_production_reconciliation_detail():
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [
                "Replace the narrated outcome edge with explicit COMMITTED, NOT_FOUND, and STILL_UNKNOWN branches."
            ],
            "revision_instruction": "Draw all three reconciliation branches.",
        },
        query="Draw an AI agent architecture with tools and memory.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["revision_instruction"] == ""
    assert review["advice"] == [
        "Production-depth hardening: Replace the narrated outcome edge with explicit COMMITTED, NOT_FOUND, and STILL_UNKNOWN branches."
    ]


def test_selected_prototype_depth_scopes_generic_production_wording():
    failure = "Split COMMITTED, NOT_FOUND, and STILL_UNKNOWN into distinct branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
        query="Design a production model-serving stack.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["advice"] == [f"Production-depth hardening: {failure}"]


def test_explicit_reconciliation_request_remains_blocking_at_prototype_depth():
    failure = "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
        query="Prototype the flow, including reconciliation after ambiguous outcomes.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_prototype_review_downgrades_production_approval_envelope_detail():
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
        query="Explain RAG and draw the runtime flow.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["advice"] == [f"Production-depth hardening: {failure}"]


def test_explicit_approval_boundary_request_remains_blocking_at_prototype_depth():
    failure = "Give every approval decision distinct approval and rejection routes."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.72,
            "blocking_failures": [failure],
        },
        query="Prototype the workflow and show its human approval boundaries.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is False
    assert review["missing"] == [failure]


def test_depth_scoping_preserves_independent_prototype_blockers():
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
        query="Draw an AI agent architecture with tools and memory.",
        resolved_complexity="prototype",
    )

    assert review["approved"] is False
    assert review["missing"] == [
        "The memory store has no directed read path back to the agent."
    ]
    assert review["revision_instruction"] == (
        "The memory store has no directed read path back to the agent."
    )
    assert len(review["advice"]) == 1


def test_production_reconciliation_failure_is_never_depth_scoped_away():
    failure = "Show COMMITTED, NOT_FOUND, and STILL_UNKNOWN reconciliation branches."
    review = _normalise_review(
        {
            "approved": False,
            "score": 0.7,
            "blocking_failures": [failure],
        },
        query="Draw the architecture.",
        resolved_complexity="production",
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


def test_complete_browser_geometry_downgrades_a_contradicted_clipping_claim():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": [
            "Re-lay out the Document Store so all edges are fully visible within the canvas, with no clipped connections."
        ],
        "revision_instruction": "Move the clipped Document Store on-screen.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is True
    assert reconciled["missing"] == []
    assert reconciled["revision_instruction"] == ""
    assert "Unreproduced visual concern" in reconciled["advice"][0]


def test_complete_browser_geometry_owns_font_scale_and_zoom_claims():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": [
            "Re-render at a larger scale so node titles and edge labels are clearly legible without zooming."
        ],
        "revision_instruction": "Increase the font size and node dimensions.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is True
    assert reconciled["missing"] == []
    assert "Unreproduced visual concern" in reconciled["advice"][0]


def test_browser_geometry_does_not_override_a_real_clipped_edge():
    graph = {"nodes": [{"id": "store"}], "edges": [{"source": "store", "target": "store"}]}
    model = _normalise_review({
        "approved": False,
        "score": 0.7,
        "blocking_failures": ["One edge is clipped outside the canvas."],
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 1,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 1,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is False
    assert reconciled["missing"] == ["One edge is clipped outside the canvas."]


def test_visual_revision_instruction_cannot_hide_a_remaining_semantic_failure():
    graph = {"nodes": [{"id": "executor"}], "edges": []}
    model = _normalise_review({
        "approved": False,
        "score": 0.6,
        "blocking_failures": [
            "Increase the font size for legibility.",
            "The executor has no rollback boundary.",
        ],
        "revision_instruction": "Zoom the canvas and use a larger font.",
    })

    reconciled = _reconcile_objective_render_claims(model, graph, {
        "screenshot_base64": "measured-image",
        "report": {
            "rendered_nodes": 1,
            "rendered_edges": 0,
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 8,
        },
    })

    assert reconciled["approved"] is False
    assert reconciled["missing"] == ["The executor has no rollback boundary."]
    assert reconciled["revision_instruction"] == "The executor has no rollback boundary."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_count", "expected_effort"),
    [(0, "medium"), (1, "low")],
)
async def test_semantic_critic_never_receives_the_rendered_image(
    monkeypatch,
    revision_count,
    expected_effort,
):
    captured = {}

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
            "screenshot_base64": "private-render-must-not-reach-the-semantic-model",
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
        "challenger_review": {
            "risks": [{"area": "safety", "risk": "Unapproved writes", "mitigation": "Approval gate"}],
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
    assert isinstance(captured["messages"][0]["content"], str)
    assert "private-render-must-not-reach-the-semantic-model" not in captured["messages"][0]["content"]
    assert "Browser layout report" not in captured["messages"][0]["content"]
    assert "Supplied evidence allowlist" in captured["messages"][0]["content"]
    assert "https://example.com" in captured["messages"][0]["content"]
    assert "Independent challenger findings" in captured["messages"][0]["content"]
    assert "Unapproved writes" in captured["messages"][0]["content"]
    assert "Do not assess or mention" in _GRAPH_CRITIC_SYSTEM


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


@pytest.mark.asyncio
async def test_semantic_critic_outage_fails_closed(monkeypatch):
    async def fail_stream_llm(**_kwargs):
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
    assert result["graph_review"]["terminal"] is True
    assert any(
        "semantic architecture review did not complete" in item
        for item in result["graph_review"]["missing"]
    )
