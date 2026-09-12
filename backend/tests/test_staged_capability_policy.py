import json

import pytest

from agent.architecture_rubric import staged_review_requirements
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation


_PREVIOUS_CAPABILITY_CRITERION = (
    "Classify capabilities from the candidate responsibilities and assumptions: "
    "external_effects means it can mutate an external system; retrieval_or_reuse "
    "means it retrieves or reuses stored artifacts; learning_or_release means "
    "feedback can change a model, prompt, ranking, or live configuration."
)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_capability_policy_checks_each_owned_effect_in_one_review(maturity):
    criterion = staged_review_requirements("components", maturity)[
        "capability_classification"
    ]

    assert criterion.startswith(_PREVIOUS_CAPABILITY_CRITERION)
    assert (
        "Check each flag independently against named component responsibilities "
        "and assumptions, and report every unsupported flag in the same review."
    ) in criterion
    assert (
        "Internal dataset curation or publication and a passive downstream consumer "
        "alone do not imply external_effects or learning_or_release."
    ) in criterion
    assert (
        "Require an owner in this system for the external write or the feedback-driven "
        "change to a model, prompt, ranking, or live configuration, respectively."
    ) in criterion


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_generation_and_gate_receive_shared_capability_policy(maturity):
    request = (
        "Draw a closed-loop evaluation system from raw feedback through validation, "
        "scoring, review, and dataset updates."
    )
    generated_prompt, _ = generation._attempt_prompt(
        stage="components",
        request=request,
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=16, edge_limit=24),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Evaluation data ownership and provenance.",
    )
    reviewed_prompt = gate._prompt(
        gate="components",
        user_request=request,
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(),
    )
    generated_criteria = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])[
        "acceptance_criteria"
    ]
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert generated_criteria == reviewed_criteria
    assert generated_criteria == staged_review_requirements("components", maturity)
    assert generated_criteria["capability_classification"] != (
        _PREVIOUS_CAPABILITY_CRITERION
    )


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_capability_clarification_invalidates_prior_review_identity(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("components", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "components":
            requirements["capability_classification"] = _PREVIOUS_CAPABILITY_CRITERION
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity


def test_production_review_consolidates_obligations_without_losing_failure_outcomes():
    requirements = staged_review_requirements(
        "connections",
        "production",
        ("state_effect_reconciliation", "retrieval_and_reuse_trust"),
    )

    assert "complete_reconciliation" not in requirements
    assert "safe_factual_failure" not in requirements
    assert "controlled_learning_and_release" not in requirements
    assert "learning_and_release" not in requirements
    reconciliation = requirements["state_effect_reconciliation"]
    for obligation in ("COMMITTED", "NOT_FOUND", "STILL_UNKNOWN", "same-key", "bounded"):
        assert obligation in reconciliation
    retrieval = requirements["retrieval_and_reuse_trust"]
    for obligation in ("rejected/stale", "abstention", "invalidation", "entailment"):
        assert obligation in retrieval


def test_production_contracts_allow_internal_ownership_without_extra_graph_edges():
    requirements = staged_review_requirements("connections", "production")

    assert "between components" in requirements["topology_enforced_guarantees"]
    assert "required interaction" in requirements["topology_enforced_guarantees"]
    assert "state_order_integrity" not in requirements
    component_requirements = staged_review_requirements("components", "production")
    assert "required internal ordering" in component_requirements["selected_depth"]
    assert "connection generation cannot change" in component_requirements["selected_depth"]
    assert "does not need a separate edge" in requirements["streaming_integrity"]
    assert "streaming_integrity" not in staged_review_requirements(
        "connections", "prototype"
    )


def test_internal_dataset_writes_keep_idempotence_and_ambiguous_commit_review():
    requirements = staged_review_requirements(
        "connections", "production", ("audit_and_provenance", "retrieval_and_reuse_trust")
    )

    assert "authorization_and_compensation" not in requirements
    reconciliation = requirements["state_effect_reconciliation"]
    for obligation in (
        "internal durable mutations", "deduplicate atomically", "same-key",
        "freshness", "fencing before execution",
    ):
        assert obligation in reconciliation
