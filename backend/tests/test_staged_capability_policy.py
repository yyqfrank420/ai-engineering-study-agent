import json
from pathlib import Path

import pytest

from agent.architecture_rubric import (
    RUBRIC_CRITERIA,
    STAGED_PRODUCTION_REQUIREMENTS,
    STAGED_REVIEW_STANDARD,
    TOPOLOGY_PROOF_REQUIREMENTS,
    staged_review_requirements,
)
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation
from agent.staged_graph_contract import production_proofs_for_capabilities


_PREVIOUS_CAPABILITY_CRITERION = (
    "Classify capabilities from the candidate responsibilities and assumptions: "
    "external_effects means it can mutate an external system; retrieval_or_reuse "
    "means it retrieves or reuses stored artifacts; learning_or_release means "
    "feedback can change a model, prompt, ranking, or live configuration."
)

_PREVIOUS_REUSE_CRITERION = (
    "Store only accepted post-gate artifacts, or route cache, replay, retry, and "
    "shortcut paths back through the required gate with identity and version scope."
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
    assert STAGED_REVIEW_STANDARD in generated_prompt
    assert STAGED_REVIEW_STANDARD in gate._GATE_SYSTEM
    assert generated_criteria == staged_review_requirements("components", maturity)
    assert generated_criteria["capability_classification"] != (
        _PREVIOUS_CAPABILITY_CRITERION
    )
    assert {"domain_specificity", "succinctness", "selected_depth"}.isdisjoint(
        generated_criteria
    )
    assert {"objective_fidelity", "brief_coverage", "mece_scope"} <= set(
        generated_criteria
    )
    schema = gate._response_schema(rule_codes=tuple(reviewed_criteria))
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]
    assert {"domain_specificity", "succinctness", "selected_depth"}.isdisjoint(codes)
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    if maturity == "production":
        assert (
            generated_input["downstream_controls"]["authorization_and_compensation"]
            == STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"]
        )
    else:
        assert "downstream_controls" not in generated_input


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_presentation_policy_invalidates_previous_component_review(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("components", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "components":
            for code in ("domain_specificity", "succinctness"):
                requirements[code] = RUBRIC_CRITERIA[code][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_presentation_policy_preserves_graph_correctness_rules(maturity):
    requirements = staged_review_requirements("connections", maturity)

    assert {
        "runtime_completeness",
        "edge_semantics",
        "safe_action_boundary",
        "gate_preserving_reuse",
    } <= set(requirements)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_mece_blocks_material_conflicts_without_requiring_extra_boxes(maturity):
    requirements = staged_review_requirements("components", maturity)
    criterion = requirements["mece_scope"]

    assert "Block conflicting material ownership" in criterion
    assert "required behavior or controls ambiguous" in criterion
    assert "outside the requested subject scope" in criterion
    assert (
        "Redundant decomposition, compatible shared ownership, and naming preferences are advisory"
        in criterion
    )
    assert "concrete behavior or control harm" in criterion
    assert "brief_coverage" in requirements
    assert "objective_fidelity" in requirements
    assert criterion != RUBRIC_CRITERIA["mece_scope"][1]


def test_production_branch_policy_keeps_required_outcomes_and_controls():
    requirements = staged_review_requirements(
        "connections", "production", tuple(TOPOLOGY_PROOF_REQUIREMENTS)
    )
    criterion = requirements["branch_completion"]

    for obligation in (
        "required or declared normal, denial, failure, alternate, and fallback path",
        "typed response carrying the applicable outcomes",
        "same executable owner handling them",
        "without a separate component or edge",
        "optional exception that the request and accepted design do not declare",
        "Block a missing required path",
        "bypasses a required control",
    ):
        assert obligation in criterion
    assert "branch_completion" not in staged_review_requirements(
        "connections", "prototype"
    )
    assert {
        "runtime_completeness",
        "edge_semantics",
        "safe_action_boundary",
        "gate_preserving_reuse",
        "topology_enforced_guarantees",
        "state_effect_reconciliation",
        *TOPOLOGY_PROOF_REQUIREMENTS,
    } <= set(requirements)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_edge_policy_keeps_required_returns_and_controls_blocking(maturity):
    criterion = staged_review_requirements("connections", maturity)["edge_semantics"]

    for obligation in (
        "compatible with their source, recipient, payload, and declared behavior",
        "Block a missing required input or answer return",
        "a contradictory direction",
        "a path that bypasses a required control",
        "An unrelated verdict or acknowledgment cannot replace required data",
        "Feedback and deployment contracts cannot substitute for required runtime or control",
    ):
        assert obligation in criterion
    assert (
        "A redundant intermediate return or duplicate description is advisory unless "
        "it changes execution or violates a required control"
    ) in criterion
    assert "identify that concrete failure when rejecting" in criterion
    assert RUBRIC_CRITERIA["edge_semantics"] == (
        "connections",
        "Give each directed edge one distinct necessary contract, consolidate duplicate "
        "interactions, and keep reverse or parallel contracts compatible. Classify each "
        "interaction by its actual behavior; feedback and deployment contracts cannot "
        "substitute for required runtime or control interactions. Each read or request "
        "that expects returned data needs its matching payload from the authoritative "
        "owner back to the requester. An unrelated reverse verdict or acknowledgment "
        "does not supply that payload.",
    )


def test_prototype_action_policy_preserves_required_controls_without_extra_stages():
    criterion = staged_review_requirements("connections", "prototype")[
        "safe_action_boundary"
    ]

    for obligation in (
        "Preserve every explicitly requested approval, audit, recovery, or other action control",
        "concrete declared external mutation",
        "appropriate authorization before the action",
        "visible failure or denial handling",
        "An existing owner may apply a lightweight guardrail before dispatch",
        "Generic educational tool or environment labels, code execution, or an external_effects flag alone",
        "Read-only tool calls and internal memory operations do not require a new approval stage unless explicitly requested",
        "Identify the concrete mutation or requested control when rejecting",
    ):
        assert obligation in criterion


def test_production_and_legacy_action_policy_retain_exact_controls():
    criterion = "Put policy, exact-action approval, audit, and recovery controls on external mutations."

    assert RUBRIC_CRITERIA["safe_action_boundary"][1] == criterion
    assert (
        staged_review_requirements("connections", "production")["safe_action_boundary"]
        == criterion
    )


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_prototype_action_policy_invalidates_only_prototype_connection_review(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "connections":
            requirements["safe_action_boundary"] = RUBRIC_CRITERIA[
                "safe_action_boundary"
            ][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    previous_identity = gate.review_identity("connections", maturity)
    assert (previous_identity != current_identity) == (maturity == "prototype")


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
    for obligation in (
        "COMMITTED",
        "NOT_FOUND",
        "STILL_UNKNOWN",
        "same-key",
        "bounded",
    ):
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
    assert set(STAGED_PRODUCTION_REQUIREMENTS).isdisjoint(component_requirements)
    assert (
        requirements["state_effect_reconciliation"]
        == (STAGED_PRODUCTION_REQUIREMENTS["state_effect_reconciliation"])
    )
    assert "streaming_integrity" not in requirements


def test_streaming_controls_require_declared_continuous_or_unbounded_delivery():
    streaming = STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]

    assert (
        "request or candidate contracts declare continuous or unbounded delivery"
        in streaming
    )
    assert (
        "Determine applicability from declared delivery behavior and completion boundaries"
        in streaming
    )
    assert (
        "Near-real-time timing, asynchronous transport, generic event ingestion, "
        "or the word 'stream' alone does not establish continuous streaming"
    ) in streaming
    assert "Cite the behavior that makes these controls necessary" in streaming
    for control in (
        "bounded backpressure",
        "ordering or event-time rules",
        "replay and deduplication",
        "late-data handling",
        "schema compatibility",
    ):
        assert control in streaming


def test_internal_dataset_writes_keep_idempotence_and_ambiguous_commit_review():
    requirements = staged_review_requirements(
        "connections",
        "production",
        ("audit_and_provenance", "retrieval_and_reuse_trust"),
    )

    assert "authorization_and_compensation" not in requirements
    reconciliation = requirements["state_effect_reconciliation"]
    for obligation in (
        "internal durable mutations",
        "deduplicate atomically",
        "same-key",
        "freshness",
        "fencing before execution",
    ):
        assert obligation in reconciliation


def test_reconciliation_scope_requires_evidence_for_each_write():
    criterion = staged_review_requirements("connections", "production")[
        "state_effect_reconciliation"
    ]

    assert criterion == STAGED_PRODUCTION_REQUIREMENTS["state_effect_reconciliation"]
    for scope in (
        "Assess each write separately",
        "Identify the retry, redelivery, competing delivery, or uncertain-commit recovery",
        "declared by the request or candidate before requiring its reconciliation protocol",
        "A durable datastore or a committed/rejected response alone does not establish that behavior",
        "an explicitly requested guarantee or a declared unsafe retry remains blocking",
    ):
        assert scope in criterion
    for control in (
        "including internal durable mutations",
        "reserve a stable operation identity durably before the effect",
        "Revalidate applicable authorization, policy, freshness, and fencing before execution",
        "deduplicate atomically at the writer",
        "COMMITTED records success",
        "NOT_FOUND permits same-key retry under valid authorization",
        "STILL_UNKNOWN has a bounded escalation",
        "Correlate late anomalies with bounded compensation",
    ):
        assert control in criterion


def test_shared_compensation_contracts_preserve_the_complete_control_path():
    criterion = staged_review_requirements(
        "connections", "production", ("authorization_and_compensation",)
    )["authorization_and_compensation"]

    assert criterion == STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"]
    assert (
        "Compensation must use the same policy, approval, execution, reconciliation, "
        "and audit controls"
    ) in criterion
    for obligation in (
        "each external effect executor, trace the exact approved action payload",
        "stable operation identity from canonical proposal or operation ownership",
        "an executor pull with its authoritative reply",
        "declared same-owner state can supply them",
        "executor may reserve the identity durably with canonical state",
        "authorization verdict or incidental reachability alone supplies neither",
    ):
        assert obligation in criterion
    assert (
        "Cover compensation explicitly in the existing validation and approval "
        "invocation and response contracts"
    ) in criterion
    assert (
        "Shared controls suffice when those contracts cover both normal and "
        "compensation actions; duplicate control paths are unnecessary"
    ) in criterion
    for obligation in (
        "Review normal and compensation behavior separately even when one component",
        "its normal input does not establish rollback initiation",
        "initiating operator, incident, event, or explicit autonomous responsibility",
        "original or applied operation reference or recovery input to its proposal producer",
        "Direct, delegated, combined, or declared same-owner internal paths are valid",
        "do not demand duplicate services or edges or an incoming edge for an explicit autonomous action",
    ):
        assert obligation in criterion
    assert (
        "Identify the compensation proposal's producer and follow its direct or "
        "delegated invocation to each shared control"
    ) in criterion
    assert (
        "A validator's broad responsibility or another producer's validation path "
        "does not establish that invocation"
    ) in criterion
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request="Design human-approved ad changes and rollback.",
        evidence_bundle={},
        resolved_maturity="production",
        candidate_records=[],
        required_production_guarantees=("authorization_and_compensation",),
    )
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert reviewed_criteria["authorization_and_compensation"] == criterion


def test_shared_owner_initiation_reaches_connection_author_and_gate():
    context = generation.AcceptedContext(
        assumptions=("A human operator may request rollback of an applied change.",),
        external_effects=True,
        retrieval_or_reuse=False,
        learning_or_release=False,
    )
    request = "Draw an approval-based campaign workflow with rollback."
    generated_prompt, _ = generation._attempt_prompt(
        stage="connections",
        request=request,
        resolved_maturity="production",
        write_set=generation.create_write_set(component_limit=4, edge_limit=8),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        accepted_components=[
            {
                "index": 0,
                "label": "Shared proposal service",
                "type": 101,
                "responsibility": "Produces normal and rollback proposals.",
                "primary_flow_member": True,
                "is_root": True,
            }
        ],
        accepted_context=context,
    )
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity="production"
    )
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request=request,
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity="production",
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert "authorization_and_compensation" in guarantees
    assert generated_input["acceptance_criteria"] == reviewed_criteria
    assert (
        reviewed_criteria["authorization_and_compensation"]
        == (STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"])
    )
    assert "normal input does not initiate rollback" in generated_prompt
    assert "normal input does not initiate rollback" in reviewed_prompt
    assert (
        "exact approved action payload and stable operation identity"
        in generated_prompt
    )
    assert (
        "exact approved action payload and stable operation identity" in reviewed_prompt
    )
    assert "declared metric pull with reply is a valid normal input" in generated_prompt
    assert "declared metric pull with reply is a valid normal input" in reviewed_prompt
    assert (
        "An authorization verdict or incidental reachability alone" in generated_prompt
    )
    assert "An authorization verdict or incidental" in reviewed_prompt


def test_captured_shared_producer_gap_records_engineering_review_evidence():
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "marketing_shared_proposal_rollback_gap.json"
        ).read_text()
    )
    graph = fixture["graph_data"]
    contract = fixture["graph_contract"]
    producer = next(node for node in graph["nodes"] if node["id"] == "n4")
    inbound = [edge for edge in graph["edges"] if edge["target"] == "n4"]

    assert fixture["capture"]["source_edge_count"] == len(graph["edges"]) == 34
    assert contract["maturity"] == "production"
    assert contract["capabilities"]["external_effects"] is True
    assert contract["component_gate"]["approved"] is True
    assert contract["connection_gate"]["approved"] is True
    assert "rollback compensation proposals" in producer["description"]
    assert any("does not act autonomously" in row for row in graph["assumptions"])
    assert {(edge["source"], edge["label"]) for edge in inbound} == {
        ("n2", "Trigger proposal generation for stored snapshot version"),
        (
            "n3",
            "Validated snapshot with provenance, or miss or stale artifact discarded in abstention",
        ),
        (
            "n5",
            "Valid: eligible for approval; invalid: rejected with constraint violations",
        ),
    }
    assert fixture["engineering_annotation"]["finding"] == (
        "missing_shared_owner_compensation_initiation"
    )
    assert fixture["engineering_annotation"]["review_origin"] == (
        "assistant_engineering_review_not_model_gate"
    )
    assert fixture["engineering_annotation"]["non_findings"] == [
        "human approval ownership",
        "primary walkthrough order",
    ]


def test_captured_executor_input_gap_separates_metric_pull_from_effect_payload():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "marketing_executor_input_gap.json"
        ).read_text()
    )
    graph = fixture["graph_data"]
    contract = fixture["graph_contract"]
    edges = graph["edges"]
    executor_inbound = [edge for edge in edges if edge["target"] == "n8"]
    proposal_inputs = [edge for edge in edges if edge["target"] == "n4"]
    reconciliation_outbound = [edge for edge in edges if edge["source"] == "n9"]

    assert set(fixture) == {
        "capture",
        "graph_data",
        "graph_contract",
        "engineering_annotation",
    }
    assert fixture["capture"]["source_edge_count"] == len(edges) == 37
    assert contract["maturity"] == "production"
    assert contract["capabilities"]["external_effects"] is True
    assert contract["component_gate"]["approved"] is True
    assert contract["connection_gate"]["approved"] is True
    assert {(edge["source"], edge["target"]) for edge in proposal_inputs} >= {
        ("n3", "n4"),
        ("n1", "n4"),
    }
    assert any(
        edge["source"] == "n4"
        and edge["target"] == "n3"
        and "Read scoped snapshots" in edge["label"]
        for edge in edges
    )
    assert {(edge["source"], edge["target"]) for edge in executor_inbound} == {
        ("n6", "n8"),
        ("n9", "n8"),
        ("n11", "n8"),
    }
    assert any(
        edge["source"] == "n6" and edge["label"].startswith("Authorized: execute")
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n9" and "same-key retry" in edge["label"]
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n11"
        and edge["label"].startswith("Committed: change applied")
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n8"
        and edge["target"] == "n11"
        and "approved exact" in edge["label"]
        for edge in edges
    )
    assert any(
        node["id"] == "n7" and "Authoritative owner" in node["description"]
        for node in graph["nodes"]
    )
    assert any(
        node["id"] == "n9" and "STILL_UNKNOWN triggers" in node["description"]
        for node in graph["nodes"]
    )
    assert not {(edge["target"]) for edge in reconciliation_outbound} & {"n1", "n4"}
    assert fixture["engineering_annotation"]["finding"] == (
        "effect_executor_lacks_approved_payload_and_identity_input"
    )
    assert fixture["engineering_annotation"]["secondary_finding"] == (
        "declared_still_unknown_compensation_lacks_initiation_path"
    )
    assert fixture["engineering_annotation"]["review_origin"] == (
        "assistant_engineering_review_not_model_gate"
    )


def test_reuse_control_details_remain_in_connection_review():
    components = staged_review_requirements("components", "production")
    connections = staged_review_requirements(
        "connections", "production", ("retrieval_and_reuse_trust",)
    )
    assert "retrieval_and_reuse_trust" not in components
    trust = connections["retrieval_and_reuse_trust"]
    for obligation in (
        "Apply each obligation to the declared retrieval or reuse path, its artifact, and its consumer",
        "A system-level retrieval_or_reuse capability does not mean every generator performs factual retrieval",
        "Identify the material factual claim or required factual-retrieval dependency",
        "apply this equally to internal and external sources",
        "Outcome-data reads and reuse for evaluation do not establish a factual-retrieval dependency for an unrelated creative generator",
        "name invalidation and revalidation ownership",
        "Discard rejected/stale artifacts",
        "Failed required factual retrieval must end in clarification, abstention, "
        "or a bounded validated retry",
        "identity, version, and provenance",
        "Shortcuts cannot bypass these controls",
    ):
        assert obligation in trust


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_depth_removal_invalidates_only_component_approval(
    monkeypatch,
    maturity,
):
    guarantees = (
        ("audit_and_provenance", "retrieval_and_reuse_trust")
        if maturity == "production"
        else ()
    )
    component_identity = gate.review_identity("components", maturity)
    connection_identity = gate.review_identity("connections", maturity, guarantees)

    def previous_depth_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "components":
            requirements["selected_depth"] = RUBRIC_CRITERIA["selected_depth"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_depth_requirements)

    assert gate.review_identity("components", maturity) != component_identity
    assert (
        gate.review_identity("connections", maturity, guarantees) == connection_identity
    )


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize("required_gate", [False, True])
def test_memory_generation_and_review_share_conditional_gate_preservation(
    maturity, required_gate
):
    request = "Draw an agent that reads and writes task memory."
    if required_gate:
        request += " Require approval before reusing stored results."
    context = generation.AcceptedContext(
        assumptions=(request,),
        external_effects=False,
        retrieval_or_reuse=True,
        learning_or_release=False,
    )
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity=maturity
    )
    generated_prompt, _ = generation._attempt_prompt(
        stage="connections",
        request=request,
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=2, edge_limit=4),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        accepted_context=context,
    )
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request=request,
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert generated_input["request"] == request
    assert generated_input["accepted_context"] == context.prompt_value()
    assert generated_input["acceptance_criteria"] == reviewed_criteria
    assert (
        reviewed_criteria["safe_action_boundary"]
        == staged_review_requirements("connections", maturity, guarantees)[
            "safe_action_boundary"
        ]
    )
    criterion = reviewed_criteria["gate_preserving_reuse"]
    assert (
        "required by the request, accepted responsibilities, or applicable maturity"
        in criterion
    )
    assert "cannot bypass those gates" in criterion
    assert "rejoin the required gate with its identity and version scope" in criterion
    assert (
        "Prototype memory or reuse alone does not require a new approval or version gate"
        in criterion
    )
    if maturity == "prototype":
        assert "retrieval_and_reuse_trust" not in reviewed_criteria
    else:
        trust = reviewed_criteria["retrieval_and_reuse_trust"]
        for obligation in (
            "entailment",
            "identity, version, and provenance",
            "invalidation",
            "Failed required factual retrieval",
            "Discard rejected/stale artifacts",
            "candidate explicitly makes example or creative reuse optional",
            "fresh generation through the same validation and approval controls",
            "Do not infer optionality or allow unsupported facts",
        ):
            assert obligation in trust


@pytest.mark.parametrize(
    "rule_code",
    [
        "audit_and_provenance",
        "retrieval_and_reuse_trust",
        "state_effect_reconciliation",
        "authorization_and_compensation",
    ],
)
def test_production_control_change_invalidates_saved_connection_approval(
    monkeypatch, rule_code
):
    guarantees = (rule_code,)
    current = gate.review_identity("connections", "production", guarantees)

    def changed_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if rule_code in requirements:
            requirements[rule_code] = "Previous control requirement"
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", changed_requirements)

    assert gate.review_identity("connections", "production", guarantees) != current


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_reuse_clarification_invalidates_prior_connection_review(monkeypatch, maturity):
    current_identity = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "connections":
            requirements["gate_preserving_reuse"] = _PREVIOUS_REUSE_CRITERION
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("connections", maturity) != current_identity


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize("stage", ["components", "connections"])
def test_streaming_guidance_is_absent_from_staged_blocking_schema(stage, maturity):
    guarantees = production_proofs_for_capabilities(
        {
            "external_effects": True,
            "retrieval_or_reuse": True,
            "learning_or_release": True,
        },
        maturity=maturity,
    )
    requirements = staged_review_requirements(stage, maturity, guarantees)
    schema = gate._response_schema(rule_codes=tuple(requirements))
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]

    assert "streaming_integrity" not in requirements
    assert "streaming_integrity" not in codes
    assert RUBRIC_CRITERIA["streaming_integrity"] == (
        "connections",
        "For continuous streams, define bounded backpressure, ordering or event-time rules, "
        "replay and deduplication ownership, late-data handling, and compatible schema evolution.",
    )
    assert (
        "bounded backpressure" in STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]
    )


def test_removing_streaming_blocker_invalidates_previous_connection_approval(
    monkeypatch,
):
    current = gate.review_identity("connections", "production")

    def previous_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "connections" and depth == "production":
            requirements["streaming_integrity"] = STAGED_PRODUCTION_REQUIREMENTS[
                "streaming_integrity"
            ]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    assert gate.review_identity("connections", "production") != current


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_edge_policy_invalidates_legacy_connection_approval(
    monkeypatch, maturity
):
    current = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "connections":
            requirements["edge_semantics"] = RUBRIC_CRITERIA["edge_semantics"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    assert gate.review_identity("connections", maturity) != current
