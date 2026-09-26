import asyncio
from itertools import product
import json
from pathlib import Path

import pytest

from agent.architecture_rubric import (
    STAGED_PRODUCTION_REQUIREMENTS,
    RUBRIC_CRITERIA,
    TOPOLOGY_PROOF_REQUIREMENTS,
    staged_review_requirements,
)
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation
from agent.staged_graph_contract import production_proofs_for_capabilities
from agent.stream_utils import StructuredLLMResponse


def _response(payload, *, finish_reason="end_turn"):
    if isinstance(payload.get("rule_reviews"), dict):
        payload = {
            **payload,
            "rule_reviews": [
                {"rule_code": code, **row} if isinstance(row, dict) else row
                for code, row in payload["rule_reviews"].items()
            ],
        }
    return StructuredLLMResponse(
        text=json.dumps(payload),
        finish_reason=finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="test",
        model="test",
    )


def _rule_reviews(rules, findings=()):
    reviews = {
        code: {
            "satisfied": True,
            "reason": "The supplied evidence satisfies this rule.",
            "record_indexes": [],
        }
        for code in rules
    }
    for finding in findings:
        reviews[finding["rule_code"]] = {
            "satisfied": False,
            "reason": finding["reason"],
            "record_indexes": finding.get("record_indexes", []),
        }
    return {"rule_reviews": reviews}


def _stub_response(monkeypatch, payload):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        if "rule_reviews" in payload:
            completed = payload
        else:
            rules = kwargs["response_schema"]["properties"]["rule_reviews"]["items"][
                "properties"
            ]["rule_code"]["enum"]
            completed = _rule_reviews(rules, payload["findings"])
            completed.update(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"approved", "findings", "checked_rules"}
                }
            )
        return _response(completed)

    monkeypatch.setattr(gate, "stream_structured_llm", fake_stream)
    return calls


def test_component_gate_uses_one_call_and_preserves_finding_indexes(monkeypatch):
    records = [{"id": "a"}, {"id": "b"}]
    calls = _stub_response(
        monkeypatch,
        {
            "approved": False,
            "findings": [
                {
                    "rule_code": "brief_coverage",
                    "reason": "The requested workflow has no owner.",
                    "record_indexes": [0],
                }
            ],
        },
    )

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={"facts": []},
            resolved_maturity="prototype",
            candidate_records=records,
        )
    )

    assert result == {
        "approved": False,
        "terminal": False,
        "findings": [
            {
                "rule_code": "brief_coverage",
                "reason": "The requested workflow has no owner.",
                "record_indexes": [0],
            }
        ],
        "diagnostics": [],
        "review_identity": gate.review_identity("components", "prototype"),
        "checked_rules": list(gate.COMPONENT_RULE_CODES),
        "rule_reviews": _rule_reviews(
            gate.COMPONENT_RULE_CODES,
            [
                {
                    "rule_code": "brief_coverage",
                    "reason": "The requested workflow has no owner.",
                    "record_indexes": [0],
                }
            ],
        )["rule_reviews"],
    }
    assert records == [{"id": "a"}, {"id": "b"}]
    assert len(calls) == 1
    assert calls[0]["provider_attempt_limit"] == 1
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"]
        == gate._COMPONENT_GATE_PROMPT_VERSION
    )


def test_component_gate_prompt_includes_capability_metadata_from_evidence(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    capabilities = {
        "external_effects": True,
        "retrieval_or_reuse": True,
        "learning_or_release": False,
    }

    result = asyncio.run(
        gate.review_components(
            user_request="Design a prototype that calls an external system.",
            evidence_bundle={"candidate_capabilities": capabilities},
            resolved_maturity="prototype",
            candidate_records=[{"label": "Gateway"}],
        )
    )

    prompt = calls[0]["messages"][0]["content"]
    assert result["approved"] is True
    assert json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0]) == {
        "candidate_capabilities": capabilities
    }
    assert "capability_classification" in prompt
    assert calls[0]["telemetry"]["metadata"]["prompt_version"] == (
        "staged_component_gate_v17"
    )
    assert (
        "architecture_context is the same bounded evidence and review frame" in prompt
    )
    assert "Resolved maturity overrides maturity wording" in prompt


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("timeout_seconds", [None, 12.5, 180.0])
def test_review_uses_explicit_timeout_independently_of_telemetry(
    monkeypatch, stage, timeout_seconds
):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )
    result = asyncio.run(
        review(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
            telemetry_context={"terminal_deadline_s": 0, "staged_attempt": -1},
            timeout_seconds=timeout_seconds,
        )
    )
    assert result["approved"] is True
    assert calls[0]["timeout_seconds"] == (
        gate.settings.staged_gate_timeout_s
        if timeout_seconds is None
        else timeout_seconds
    )
    assert calls[0]["provider_attempt_limit"] == 1


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize(
    "timeout_seconds", [0, -1, True, "55", float("inf"), float("nan")]
)
def test_invalid_review_timeout_is_rejected_before_provider(
    monkeypatch, stage, timeout_seconds
):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )
    with pytest.raises(ValueError, match="timeout_seconds"):
        asyncio.run(
            review(
                user_request="Design a service.",
                evidence_bundle={},
                resolved_maturity="prototype",
                candidate_records=[],
                timeout_seconds=timeout_seconds,
            )
        )
    assert calls == []


def test_staged_component_gate_excludes_rules_without_upstream_review():
    assert "independent_risk_coverage" in RUBRIC_CRITERIA
    assert "independent_risk_coverage" not in gate.COMPONENT_RULE_CODES


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_gate_acceptance_uses_named_subject_scope(maturity):
    requirements = staged_review_requirements("components", maturity)
    objective = requirements["objective_fidelity"]
    assert (
        "A named educational, research, or comparison subject establishes diagram scope "
        "without an invented business use case"
    ) in objective
    assert (
        "For an applied system design, establish the user's business domain"
        in objective
    )
    assert "do not ask whether a diagram is wanted" in objective
    prompt = gate._prompt(
        gate="components",
        user_request=(
            "Research current practical trade-offs between agents and fixed workflows "
            "for production AI products."
        ),
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(),
    )
    assert objective in prompt
    assert "objective_fidelity" not in staged_review_requirements(
        "connections", maturity
    )


def test_unknown_production_guarantee_is_rejected_before_provider_call(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    with pytest.raises(ValueError, match="unknown production guarantee"):
        asyncio.run(
            gate.review_connections(
                user_request="Design a service.",
                evidence_bundle={},
                resolved_maturity="production",
                candidate_records=[],
                required_production_guarantees=["invented"],
            )
        )
    assert calls == []


@pytest.mark.parametrize(
    ("stage", "maturity", "flags"),
    [
        ("components", maturity, (False, False, False))
        for maturity in ("prototype", "production")
    ]
    + [
        ("connections", maturity, flags)
        for maturity in ("prototype", "production")
        for flags in product((False, True), repeat=3)
    ],
)
def test_initial_generation_and_gate_share_every_applicable_requirement(
    stage, maturity, flags
):
    context = generation.AcceptedContext((), *flags)
    guarantees = (
        production_proofs_for_capabilities(
            context.prompt_value()["capabilities"], maturity=maturity
        )
        if stage == "connections"
        else []
    )
    generated_prompt, _ = generation._attempt_prompt(
        stage=stage,
        request="Design the requested system.",
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=4, edge_limit=6),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        accepted_context=context if stage == "connections" else None,
        architecture_context="Evidence frame." if stage == "components" else None,
    )
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    generated_criteria = generated_input["acceptance_criteria"]
    rules = (
        gate.COMPONENT_RULE_CODES
        if stage == "components"
        else gate._rules_for_connections(maturity, guarantees)
    )
    reviewed_prompt = gate._prompt(
        gate=stage,
        user_request="Design the requested system.",
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert generated_criteria == reviewed_criteria
    assert generated_criteria == staged_review_requirements(stage, maturity, guarantees)
    assert set(generated_criteria) == set(rules)
    assert set(guarantees) <= set(rules)
    assert "independent_risk_coverage" not in generated_criteria
    assert "selected_depth" not in generated_criteria
    assert "streaming_integrity" not in generated_criteria
    schema = gate._response_schema(rule_codes=tuple(rules))
    assert (
        "streaming_integrity"
        not in schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
            "enum"
        ]
    )
    if maturity == "production":
        guidance_key = (
            "downstream_controls" if stage == "components" else "authoring_guidance"
        )
        assert (
            generated_input[guidance_key]["streaming_integrity"]
            == (STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"])
        )
    if stage == "components":
        assert (
            "Depict the requested subject" in generated_criteria["objective_fidelity"]
        )
        assert (
            "explain, cite or ground the response in sources, or draw its flow"
            in generated_criteria["objective_fidelity"]
        )
        assert (
            "only when explicitly requested as system features"
            in generated_criteria["objective_fidelity"]
        )
        assert (
            "response instructions do not create runtime responsibilities"
            in generated_criteria["brief_coverage"]
        )
        assert (
            "Mechanics used to author this response are not runtime features unless "
            "explicitly requested" in generated_criteria["mece_scope"]
        )
    for code, requirement in generated_criteria.items():
        if (
            stage == "connections"
            and maturity == "production"
            and code == "topology_enforced_guarantees"
        ):
            assert "between components" in requirement
            assert "internal operations" in requirement
        elif (
            stage == "connections"
            and maturity == "production"
            and code in STAGED_PRODUCTION_REQUIREMENTS
        ):
            assert requirement == STAGED_PRODUCTION_REQUIREMENTS[code]
        elif (
            stage == "connections"
            and maturity == "prototype"
            and code == "safe_action_boundary"
        ):
            assert "concrete declared external mutation" in requirement
            assert "Preserve every explicitly requested" in requirement
        elif stage == "connections" and code == "edge_semantics":
            assert "Block a missing required input or answer return" in requirement
            assert "a path that bypasses a required control" in requirement
            assert "duplicate description is advisory unless" in requirement
        elif stage == "components" and code == "mece_scope":
            assert "Block conflicting material ownership" in requirement
            assert "naming preferences are advisory" in requirement
        elif stage == "connections" and code == "branch_completion":
            assert "Block a missing required path" in requirement
            assert "without a separate component or edge" in requirement
        elif code in RUBRIC_CRITERIA:
            assert requirement == RUBRIC_CRITERIA[code][1]
        elif code in TOPOLOGY_PROOF_REQUIREMENTS:
            assert requirement == TOPOLOGY_PROOF_REQUIREMENTS[code]
        else:
            assert code == "capability_classification"
            assert "external_effects" in requirement


def test_unknown_rule_cannot_silently_approve(monkeypatch):
    _stub_response(
        monkeypatch,
        {
            "approved": True,
            "findings": [
                {
                    "rule_code": "invented",
                    "reason": "Unsupported",
                    "record_indexes": [0],
                }
            ],
        },
    )

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[{"id": "a"}],
        )
    )

    assert result["approved"] is False
    assert result["terminal"] is True
    assert result["findings"] == []
    assert result["diagnostics"] == [
        "provider response has an incomplete or unknown rule review"
    ]


def test_malformed_top_level_response_is_terminal(monkeypatch):
    _stub_response(monkeypatch, {"approved": True, "findings": [], "score": 1})

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["approved"] is False
    assert result["terminal"] is True
    assert result["findings"] == []


@pytest.mark.parametrize("satisfied", [True, False])
def test_rule_requires_reason_even_when_satisfied(monkeypatch, satisfied):
    payload = _rule_reviews(gate.COMPONENT_RULE_CODES)
    payload["rule_reviews"]["brief_coverage"] = {
        "satisfied": satisfied,
        "reason": " ",
        "record_indexes": [],
    }
    _stub_response(monkeypatch, payload)
    result = asyncio.run(
        gate.review_components(
            user_request="Review",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )
    assert result["terminal"] is True
    assert result["approved"] is False
    assert result["findings"] == []
    assert result["diagnostics"] == ["invalid review reason for brief_coverage"]


def test_prototype_connection_schema_excludes_production_rules(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})

    result = asyncio.run(
        gate.review_connections(
            user_request="Design a prototype.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
            required_production_guarantees=["audit_and_provenance"],
        )
    )

    schema = calls[0]["response_schema"]
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]
    assert result["approved"] is True
    assert "production_proofs" not in schema["properties"]
    assert "topology_enforced_guarantees" not in codes
    assert "audit_and_provenance" not in codes
    assert "logical_flow" not in codes
    assert "branch_completion" not in codes


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_connection_schema_keeps_runtime_completeness(monkeypatch, maturity):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})

    result = asyncio.run(
        gate.review_connections(
            user_request="Design an observation-only service.",
            evidence_bundle={},
            resolved_maturity=maturity,
            candidate_records=[],
        )
    )

    schema = calls[0]["response_schema"]
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]

    assert result["approved"] is True
    assert "runtime_completeness" in codes


def test_connection_gate_prompt_scopes_runtime_completeness_to_accepted_context(
    monkeypatch,
):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    candidate_context = {
        "capabilities": {"external_effects": False},
        "assumptions": ["Telemetry is retained durably."],
    }
    components = [
        {"id": "collector", "responsibility": "Collect observations."},
        {"id": "telemetry", "responsibility": "Persist telemetry durably."},
    ]

    result = asyncio.run(
        gate.review_connections(
            user_request="Design an observation-only service.",
            evidence_bundle={
                "candidate_context": candidate_context,
                "candidate_components": components,
            },
            resolved_maturity="prototype",
            candidate_records=[
                {"source": "collector", "target": "telemetry", "label": "event"}
            ],
        )
    )

    prompt = calls[0]["messages"][0]["content"]

    assert result["approved"] is True
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"]
        == "staged_connection_gate_v24"
    )
    assert "candidate_context.capabilities" in prompt
    assert "candidate_context.assumptions" in prompt
    assert "candidate component responsibilities" in prompt
    assert "Resolved maturity remains authoritative." in prompt
    assert "a durable telemetry sink is a complete outcome" in prompt
    assert "An unclassified record has unknown role" in prompt
    assert "rejecting it for missing pairing metadata" in prompt
    assert "an actual invocation contract to the retry owner" in prompt
    assert "autonomous poller or same-owner internal action" in prompt
    assert "normal input does not initiate rollback" in prompt
    assert "original or applied operation reference" in prompt
    assert "Combined contracts can cover both" in prompt
    assert "when compensation is required or declared" in prompt
    assert "a satisfied reason must identify both initiation witnesses" in prompt
    assert "An unsatisfied reason must identify each missing" in prompt
    assert "declared metric pull with reply is a valid normal input" in prompt
    assert "do not demand a redundant push or timer" in prompt
    assert "stable operation identity from canonical proposal" not in prompt


@pytest.mark.parametrize(
    ("maturity", "guarantees", "external_effects", "requires_identity"),
    [
        ("prototype", (), True, False),
        ("production", (), False, False),
        ("production", ("authorization_and_compensation",), True, True),
    ],
)
def test_executor_identity_proof_applies_only_to_selected_production_guarantee(
    maturity, guarantees, external_effects, requires_identity
):
    prompt = gate._prompt(
        gate="connections",
        user_request="Design a service that writes approved ad changes.",
        evidence_bundle={
            "candidate_context": {
                "capabilities": {"external_effects": external_effects}
            }
        },
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    criteria = json.loads(prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])

    assert (
        "For each required action, check its actual trigger or change input" in prompt
    )
    assert "declared metric pull with reply is a valid normal input" in prompt
    if requires_identity:
        assert "authorization_and_compensation" in criteria
        assert "exact approved action payload and stable operation identity" in prompt
        assert "An authorization verdict or incidental reachability alone" in prompt
        assert (
            "an unsatisfied reason must name the missing payload or identity" in prompt
        )
    else:
        assert "authorization_and_compensation" not in criteria
        assert "stable operation identity from canonical proposal" not in prompt
        assert "both effect-input witnesses per executor" not in prompt
    if maturity == "prototype":
        assert (
            "appropriate authorization before the action"
            in criteria["safe_action_boundary"]
        )
        assert "visible failure or denial handling" in criteria["safe_action_boundary"]


def test_connection_gate_receives_request_scoped_exchange_evidence(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    pairs = [{"request_record_index": 0, "response_record_index": 1}]
    records = [
        {"source": "caller", "target": "worker", "label": "requests work"},
        {"source": "worker", "target": "caller", "label": "returns outcome"},
    ]

    result = asyncio.run(
        gate.review_connections(
            user_request="Design a retryable workflow.",
            evidence_bundle={"connection_exchanges": pairs},
            resolved_maturity="prototype",
            candidate_records=records,
        )
    )

    prompt = calls[0]["messages"][0]["content"]
    evidence = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    assert result["approved"] is True
    assert len(calls) == 1
    assert evidence["connection_exchanges"] == pairs
    assert "A paired reply or incidental reachability cannot invoke" in prompt
    assert "proposal producer's exact-action presentation" in prompt
    assert "When human review or human approval is requested or declared" in prompt
    assert "human review surface or declared human decision boundary" in prompt
    assert "via a direct or delegated contract" in prompt
    assert "forward contract (which may be a request, event, or write)" in prompt
    assert "response_record_index is its explicit paired reply" in prompt
    assert "Pairing does not prove the forward contract's semantic role" in prompt


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_compensation_human_review_prompt_is_conditional(maturity):
    prompt = gate._prompt(
        gate="connections",
        user_request="Design an autonomous guarded rollback without human approval.",
        evidence_bundle={"candidate_components": [], "candidate_context": {}},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(
            ("authorization_and_compensation",) if maturity == "production" else ()
        ),
    )
    criteria = json.loads(prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])

    assert (
        "When human review or human approval is requested or declared for compensation"
    ) in prompt
    assert "In that case, a returned approval verdict alone" in prompt
    if maturity == "prototype":
        assert "authorization_and_compensation" not in criteria
        assert (
            "a separate approval stage is not required unless explicitly requested"
            in criteria["safe_action_boundary"]
        )
    else:
        assert "authorization_and_compensation" in criteria


@pytest.mark.parametrize("stage", ["components", "connections"])
def test_overview_prompt_preserves_maturity_objective_and_required_controls(stage):
    guarantees = tuple(TOPOLOGY_PROOF_REQUIREMENTS) if stage == "connections" else ()
    prompt = gate._prompt(
        gate=stage,
        user_request="Design a production payment service with exact-action approval.",
        evidence_bundle={"candidate_context": {"detail_level": "overview"}},
        resolved_maturity="production",
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    requirements = json.loads(
        prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert "The candidate requests an overview." in prompt
    assert "Presentation simplification may omit optional detail only." in prompt
    assert "does not change the resolved maturity, objective" in prompt
    assert "requested behavior, required directed interactions" in prompt
    assert "detail_level is presentation context, not evidence" in prompt
    assert "Resolved maturity: production" in prompt
    assert requirements == staged_review_requirements(stage, "production", guarantees)
    if stage == "components":
        assert {"objective_fidelity", "brief_coverage", "mece_scope"} <= set(
            requirements
        )
    else:
        assert {
            "runtime_completeness",
            "edge_semantics",
            "safe_action_boundary",
            "branch_completion",
            *guarantees,
        } <= set(requirements)


@pytest.mark.parametrize(
    "evidence_bundle",
    [
        {},
        {"detail_level": "overview"},
        {"candidate_context": {"detail_level": "detailed"}},
        {"candidate_context": "overview"},
    ],
)
def test_overview_guidance_requires_exact_candidate_context(evidence_bundle):
    prompt = gate._prompt(
        gate="components",
        user_request="Design the service.",
        evidence_bundle=evidence_bundle,
        resolved_maturity="prototype",
        candidate_records=[],
        required_production_guarantees=(),
    )

    assert "The candidate requests an overview." not in prompt
    assert "brief_coverage" in prompt


@pytest.mark.parametrize(
    ("stage", "rule"),
    [
        ("components", "brief_coverage"),
        ("components", "mece_scope"),
        ("connections", "branch_completion"),
        ("connections", "safe_action_boundary"),
        ("connections", "authorization_and_compensation"),
    ],
)
def test_overview_metadata_cannot_approve_an_unsatisfied_rule(monkeypatch, stage, rule):
    finding = {
        "rule_code": rule,
        "reason": "The required path or responsibility is missing.",
        "record_indexes": [0],
    }
    _stub_response(monkeypatch, {"approved": True, "findings": [finding]})
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )
    result = asyncio.run(
        review(
            user_request="Design a production payment service.",
            evidence_bundle={"candidate_context": {"detail_level": "overview"}},
            resolved_maturity="production",
            candidate_records=[{"label": "Payment service"}],
            **(
                {"required_production_guarantees": tuple(TOPOLOGY_PROOF_REQUIREMENTS)}
                if stage == "connections"
                else {}
            ),
        )
    )

    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["findings"] == [finding]
    assert rule in result["checked_rules"]


def test_runtime_completeness_allows_observation_only_telemetry_outcome():
    assert RUBRIC_CRITERIA["runtime_completeness"] == (
        "connections",
        "Connect observations and accepted processing to measurable outcomes. Require "
        "decisions and actions only when accepted component responsibilities own them. For "
        "observation-only designs, a durable telemetry sink is a complete outcome. "
        "For every requested behavior, identify the owner and its actual trigger or "
        "change-input contract. A read, response, or incidental reachability does not "
        "invoke an unrelated write or adjustment.",
    )


def test_production_connection_schema_preserves_hard_rules(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})

    result = asyncio.run(
        gate.review_connections(
            user_request="Design a production service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[{"source": "a", "target": "b"}],
        )
    )

    schema = calls[0]["response_schema"]
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]

    assert result["approved"] is True
    assert "logical_flow" in codes
    assert "branch_completion" in codes


@pytest.mark.parametrize("invalid_audit", ["missing", "unknown", "not_object"])
def test_gate_rejects_an_incomplete_rule_audit(monkeypatch, invalid_audit):
    payload = _rule_reviews(gate.COMPONENT_RULE_CODES)
    if invalid_audit == "missing":
        payload["rule_reviews"].pop("brief_coverage")
    elif invalid_audit == "unknown":
        payload["rule_reviews"]["invented"] = payload["rule_reviews"]["brief_coverage"]
    else:
        payload["rule_reviews"] = []
    _stub_response(monkeypatch, payload)
    result = asyncio.run(
        gate.review_components(
            user_request="Review",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )
    assert result["terminal"] is True
    assert result["diagnostics"] == [
        "provider response has an incomplete or unknown rule review"
    ]


@pytest.mark.parametrize("stage", ["components", "connections"])
def test_successful_review_retains_identity_and_complete_rule_audit(monkeypatch, stage):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )

    result = asyncio.run(
        review(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["review_identity"] == gate.review_identity(stage, "prototype")
    assert (
        result["checked_rules"]
        == calls[0]["response_schema"]["properties"]["rule_reviews"]["items"][
            "properties"
        ]["rule_code"]["enum"]
    )
    assert len(result["review_identity"]) == 64


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize(
    "change", ["model", "temperature", "effort", "prompt_version", "rubric", "schema"]
)
def test_review_identity_invalidates_changed_review_policy(monkeypatch, stage, change):
    baseline = gate.review_identity(stage, "production")
    assert gate.review_identity(stage, "production") == baseline
    if change == "model":
        monkeypatch.setattr(gate.settings, "graph_qa_model", "different-review-model")
    elif change == "temperature":
        monkeypatch.setattr(
            gate.settings, "graph_temperature", gate.settings.graph_temperature + 0.1
        )
    elif change == "effort":
        monkeypatch.setattr(gate, "_GATE_EFFORT", "high")
    elif change == "prompt_version":
        field = (
            "_COMPONENT_GATE_PROMPT_VERSION"
            if stage == "components"
            else "_CONNECTION_GATE_PROMPT_VERSION"
        )
        monkeypatch.setattr(gate, field, "next-release")
    elif change == "rubric":
        requirements = gate.staged_review_requirements

        def revised_requirements(*args):
            current = requirements(*args)
            rule = next(iter(current))
            return {**current, rule: "Revised acceptance requirement."}

        monkeypatch.setattr(gate, "staged_review_requirements", revised_requirements)
    else:
        monkeypatch.setattr(gate, "_MAX_RECORD_INDEXES", gate._MAX_RECORD_INDEXES + 1)

    assert gate.review_identity(stage, "production") != baseline


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize(
    ("rule", "previous_requirement"),
    [
        (
            "objective_fidelity",
            "Make the requested goal and constraints visible in component responsibilities.",
        ),
        (
            "brief_coverage",
            "Give every requested responsibility a component owner.",
        ),
    ],
)
def test_subject_runtime_policy_invalidates_previous_component_review_identity(
    monkeypatch, maturity, rule, previous_requirement
):
    current_identity = gate.review_identity("components", maturity)

    monkeypatch.setitem(RUBRIC_CRITERIA, rule, ("components", previous_requirement))

    assert gate.review_identity("components", maturity) != current_identity


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_mece_policy_invalidates_previous_component_review_identity(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("components", maturity)
    current_requirements = gate.staged_review_requirements

    def previous_requirements(stage, depth, guarantees=()):
        requirements = current_requirements(stage, depth, guarantees)
        if stage == "components":
            requirements["mece_scope"] = RUBRIC_CRITERIA["mece_scope"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity


def test_review_identity_tracks_only_applicable_production_obligations():
    guarantee = ["audit_and_provenance"]
    assert gate.review_identity("components", "prototype", guarantee) == (
        gate.review_identity("components", "prototype")
    )
    assert gate.review_identity("connections", "prototype", guarantee) == (
        gate.review_identity("connections", "prototype")
    )
    assert gate.review_identity("connections", "production", guarantee) != (
        gate.review_identity("connections", "production")
    )
    assert gate.review_identity("connections", "production", guarantee * 2) == (
        gate.review_identity("connections", "production", guarantee)
    )
    assert gate.review_identity("components", "prototype") != (
        gate.review_identity("components", "production")
    )
    with pytest.raises(ValueError, match="gate must be"):
        gate.review_identity("unknown", "prototype")
    with pytest.raises(ValueError, match="resolved_maturity"):
        gate.review_identity("components", "unknown")


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("trusted", [True, False, None, "true"])
def test_edit_review_scope_preserves_baseline_context_and_full_candidate(
    monkeypatch, stage, trusted
):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    scope = {
        "trusted_baseline": trusted,
        "baseline_records": [{"id": "retained"}, {"id": "removed"}],
        "baseline_context": {
            "title": "Payment processing",
            "assumptions": ["The ledger is authoritative."],
        },
        "changed_record_indexes": [1],
        "removed_ids": ["removed"],
        "editable_fields": ["label"],
    }
    records = [{"id": "retained"}, {"id": "changed"}]
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )

    result = asyncio.run(
        review(
            user_request="Rename this component.",
            evidence_bundle={"review_scope": scope},
            resolved_maturity="prototype",
            candidate_records=records,
        )
    )

    prompt = calls[0]["messages"][0]["content"]
    evidence = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    reviewed_records = json.loads(
        prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0]
    )
    assert result["approved"] is True
    assert evidence["review_scope"] == scope
    assert reviewed_records == [
        {"record_index": index, "record": record}
        for index, record in enumerate(records)
    ]
    assert "original title and assumptions" in prompt
    assert "Finding indexes refer to the full current candidate records" in prompt
    if trusted is True:
        assert "Do not reopen unrelated unchanged baseline design decisions" in prompt
        assert "regressions and affected dependencies" in prompt
        assert "New evidence that contradicts a baseline premise reopens" in prompt
        assert (
            "Changed capabilities, assumptions, responsibilities, or global obligations"
            in prompt
        )
        assert (
            "Report every blocking regression even outside the editable fields"
            in prompt
        )
        assert "Perform a full review" not in prompt
    else:
        assert "Perform a full review of all current candidate records" in prompt
        assert (
            "Do not reopen unrelated unchanged baseline design decisions" not in prompt
        )


def test_scoped_review_preserves_blockers_outside_changed_records(
    monkeypatch,
):
    _stub_response(
        monkeypatch,
        {
            "approved": True,
            "findings": [
                {
                    "rule_code": "runtime_completeness",
                    "reason": "The edit disconnects the retained outcome.",
                    "record_indexes": [2],
                }
            ],
        },
    )

    result = asyncio.run(
        gate.review_connections(
            user_request="Change the input route.",
            evidence_bundle={
                "review_scope": {
                    "trusted_baseline": True,
                    "changed_record_indexes": [0],
                    "editable_fields": ["label"],
                }
            },
            resolved_maturity="production",
            candidate_records=[
                {"source": "input", "target": "service"},
                {"source": "service", "target": "audit"},
                {"source": "audit", "target": "outcome"},
            ],
            required_production_guarantees=["audit_and_provenance"],
        )
    )

    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["findings"][0]["record_indexes"] == [2]


@pytest.mark.parametrize(
    "row",
    [
        None,
        [],
        {},
        {"satisfied": True, "reason": "Missing indexes"},
        {"satisfied": 1, "reason": "Invalid boolean", "record_indexes": []},
        {"satisfied": "false", "reason": "Invalid boolean", "record_indexes": []},
        {"satisfied": False, "reason": None, "record_indexes": []},
        {"satisfied": True, "reason": "Valid", "record_indexes": [], "score": 1},
        *[
            {"satisfied": False, "reason": "Bad index", "record_indexes": indexes}
            for indexes in (None, "0", [1], [True], [-1], [0.0], [0] * 33)
        ],
    ],
)
def test_malformed_rule_reviews_fail_terminally(monkeypatch, row):
    payload = _rule_reviews(gate.COMPONENT_RULE_CODES)
    payload["rule_reviews"]["brief_coverage"] = row
    _stub_response(monkeypatch, payload)
    result = asyncio.run(
        gate.review_components(
            user_request="Review",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[{"id": "a"}],
        )
    )
    assert result["approved"] is False
    assert result["terminal"] is True
    assert result["findings"] == []
    assert "rule_reviews" not in result


@pytest.mark.parametrize("duplicate_at", ["top", "rule", "field"])
def test_duplicate_json_review_keys_fail_closed(duplicate_at):
    rules = ("brief_coverage",)
    row = '{"satisfied":true,"reason":"Owned here","record_indexes":[]}'
    text = '{"rule_reviews":{"brief_coverage":' + row + "}}"
    if duplicate_at == "top":
        text = text[:-1] + ',"rule_reviews":{}}'
    elif duplicate_at == "rule":
        text = (
            '{"rule_reviews":{"brief_coverage":'
            + row
            + ',"brief_coverage":'
            + row
            + "}}"
        )
    else:
        text = text.replace('"satisfied":true', '"satisfied":false,"satisfied":true')
    response = _response({})
    response = StructuredLLMResponse(
        text=text,
        finish_reason=response.finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="test",
        model="test",
    )
    result = gate._review_result(
        response,
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=[],
    )
    assert result["terminal"] is True
    assert result["diagnostics"] == ["provider response is not valid JSON"]


def test_old_approval_response_is_not_a_supported_provider_shape():
    rules = gate.COMPONENT_RULE_CODES
    result = gate._review_result(
        _response({"approved": True, "checked_rules": list(rules), "findings": []}),
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=[],
    )
    assert result["terminal"] is True
    assert result["diagnostics"] == ["provider response has an invalid top-level shape"]


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("variant", ["create", "trusted_edit", "untrusted_edit"])
def test_review_identity_binds_actual_prompt_content(monkeypatch, stage, variant):
    baseline = gate.review_identity(stage, "prototype")
    original_prompt = gate._prompt

    def changed_prompt(**kwargs):
        prompt = original_prompt(**kwargs)
        scope = kwargs["evidence_bundle"].get("review_scope")
        current_variant = (
            "create"
            if scope is None
            else "trusted_edit"
            if scope["trusted_baseline"]
            else "untrusted_edit"
        )
        return (
            prompt + " Revised instruction." if current_variant == variant else prompt
        )

    monkeypatch.setattr(gate, "_prompt", changed_prompt)

    assert gate.review_identity(stage, "prototype") != baseline


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("approved", [True, False])
def test_protected_evaluation_captures_exact_review_inputs_and_result(
    monkeypatch, stage, approved
):
    monkeypatch.setattr(gate.settings, "evaluation_run_id", " review-eval-1 ")
    monkeypatch.setattr(
        gate.settings, "internal_test_email_allowlist_raw", "internal@example.com"
    )
    findings = (
        []
        if approved
        else [
            {
                "rule_code": (
                    "brief_coverage"
                    if stage == "components"
                    else "runtime_completeness"
                ),
                "reason": "The candidate omits the requested outcome.",
                "record_indexes": [0],
            }
        ]
    )
    _stub_response(monkeypatch, {"approved": approved, "findings": findings})
    events = []

    async def send(event):
        events.append(event)

    records = [{"id": "candidate-a", "responsibility": "Own the outcome."}]
    evidence = {"candidate_context": {"title": "Service", "assumptions": []}}
    review = (
        gate.review_components if stage == "components" else gate.review_connections
    )
    result = asyncio.run(
        review(
            user_request="Design the service.",
            evidence_bundle=evidence,
            resolved_maturity="prototype",
            candidate_records=records,
            telemetry_context={
                "user_email": " INTERNAL@example.com ",
                "is_production": False,
                "staged_attempt": 1,
                "send": send,
                "token": "credential-must-never-be-captured",
                "internal_context": "context-must-never-be-captured",
            },
        )
    )

    assert len(events) == 1
    assert events[0]["type"] == "workflow_progress"
    assert events[0]["phase"] == "review"
    assert events[0]["status"] == ("complete" if approved else "rejected")
    assert events[0]["review_capture"] == {
        "schema_version": 1,
        "evaluation_run_id": "review-eval-1",
        "stage": stage,
        "attempt": 1,
        "review_identity": result["review_identity"],
        "user_request": "Design the service.",
        "evidence_bundle": evidence,
        "candidate_records": records,
        "result": result,
        "finish_reason": "end_turn",
    }
    capture_text = json.dumps(events)
    assert "credential-must-never-be-captured" not in capture_text
    assert "context-must-never-be-captured" not in capture_text
    assert "telemetry_context" not in capture_text
    assert "input_tokens" not in capture_text
    events[0]["review_capture"]["result"]["approved"] = not approved
    events[0]["review_capture"]["candidate_records"][0]["id"] = "mutated"
    events[0]["review_capture"]["evidence_bundle"]["candidate_context"]["title"] = (
        "mutated"
    )
    assert result["approved"] is approved
    assert records[0]["id"] == "candidate-a"
    assert evidence["candidate_context"]["title"] == "Service"


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize(
    ("run_id", "email", "production", "allowlist"),
    [
        ("eval-1", "ordinary@example.com", False, "internal@example.com"),
        ("eval-1", "internal@example.com", True, "internal@example.com"),
        ("", "internal@example.com", False, "internal@example.com"),
        ("  ", "internal@example.com", False, "internal@example.com"),
        ("eval-1", "", False, "internal@example.com"),
        ("eval-1", "internal@example.com", False, ""),
    ],
)
def test_review_capture_requires_every_protected_evaluation_condition(
    monkeypatch, run_id, email, production, allowlist, terminal
):
    monkeypatch.setattr(gate.settings, "evaluation_run_id", run_id)
    monkeypatch.setattr(gate.settings, "internal_test_email_allowlist_raw", allowlist)
    _stub_response(
        monkeypatch,
        {"rule_reviews": {}} if terminal else {"approved": True, "findings": []},
    )
    events = []

    async def send(event):
        events.append(event)

    result = asyncio.run(
        gate.review_components(
            user_request="Design the service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
            telemetry_context={
                "user_email": email,
                "is_production": production,
                "send": send,
            },
        )
    )

    assert result["approved"] is not terminal
    assert result["terminal"] is terminal
    assert events == []


@pytest.mark.parametrize(
    ("failure", "diagnostic"),
    [
        ("provider", "provider call failed: RuntimeError"),
        ("unfinished", "provider response did not complete"),
        ("json", "provider response is not valid JSON"),
        ("shape", "provider response has an invalid top-level shape"),
        ("fields", "provider response has an incomplete or unknown rule review"),
        ("finding", "provider response has an incomplete or unknown rule review"),
        ("empty_reason", "invalid review reason for brief_coverage"),
    ],
)
def test_terminal_review_capture_retains_diagnostic_without_raw_response(
    monkeypatch, failure, diagnostic
):
    monkeypatch.setattr(gate.settings, "evaluation_run_id", "eval-1")
    monkeypatch.setattr(
        gate.settings, "internal_test_email_allowlist_raw", "internal@example.com"
    )

    async def fake_stream(**kwargs):
        if failure == "provider":
            raise RuntimeError("private provider error")
        payload = _rule_reviews(
            kwargs["response_schema"]["properties"]["rule_reviews"]["items"][
                "properties"
            ]["rule_code"]["enum"]
        )
        if failure == "shape":
            payload["unexpected"] = "private provider text"
        elif failure == "fields":
            payload["rule_reviews"] = {}
        elif failure == "finding":
            payload["rule_reviews"]["unknown"] = {
                "satisfied": False,
                "reason": "Invalid.",
                "record_indexes": [],
            }
        elif failure == "empty_reason":
            payload["rule_reviews"]["brief_coverage"]["reason"] = ""
        response = _response(
            payload,
            finish_reason="max_tokens" if failure == "unfinished" else "end_turn",
        )
        if failure == "json":
            return StructuredLLMResponse(
                text="private malformed provider text",
                finish_reason="end_turn",
                input_tokens=1,
                output_tokens=1,
                provider="test",
                model="test",
            )
        return response

    monkeypatch.setattr(gate, "stream_structured_llm", fake_stream)
    events = []

    async def send(event):
        events.append(event)

    review = gate.review_components
    result = asyncio.run(
        review(
            user_request="Design the service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
            telemetry_context={
                "user_email": "internal@example.com",
                "send": send,
                "staged_attempt": 1,
            },
        )
    )

    assert result["terminal"] is True
    assert result["diagnostics"] == [diagnostic]
    assert len(events) == 1
    capture = events[0]["review_capture"]
    assert events[0]["status"] == "rejected"
    assert capture["result"] == result
    assert capture["review_identity"] == result["review_identity"]
    assert capture["attempt"] == 1
    if failure == "provider":
        assert "finish_reason" not in capture
    else:
        assert capture["finish_reason"] == (
            "max_tokens" if failure == "unfinished" else "end_turn"
        )
    assert "private" not in json.dumps(events)


def test_recovered_component_rejection_remains_actionable(monkeypatch):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_gate_34649724600.json"
        ).read_text()
    )
    calls = _stub_response(monkeypatch, fixture["response"])

    result = asyncio.run(
        gate.review_components(
            user_request="Expand monitoring with one directly connected responsibility.",
            evidence_bundle={},
            resolved_maturity=fixture["resolved_maturity"],
            candidate_records=[
                {"id": f"n{index + 1}"}
                for index in range(fixture["candidate_record_count"])
            ],
        )
    )

    assert len(calls) == 1
    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["findings"] == fixture["response"]["findings"]
    reason = result["findings"][0]["reason"]
    assert len(reason) == 538
    assert "anchored at n6" in reason
    assert "actual data source" in reason
    assert "telemetry query path to n5" in reason
    assert result["diagnostics"] == []


@pytest.mark.parametrize("approved", [True, False])
def test_reason_storage_bound_preserves_rejection_with_explicit_diagnostic(
    monkeypatch, approved
):
    _stub_response(
        monkeypatch,
        {
            "approved": approved,
            "findings": [
                {
                    "rule_code": "mece_scope",
                    "reason": "x" * (gate._MAX_REASON_CHARS + 1),
                }
            ],
        },
    )

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["approved"] is False
    assert result["terminal"] is False
    assert len(result["findings"][0]["reason"]) == gate._MAX_REASON_CHARS
    assert result["diagnostics"][0] == (
        f"review reason for mece_scope truncated to {gate._MAX_REASON_CHARS} characters"
    )


@pytest.mark.parametrize("approved", [True, False])
def test_review_capture_send_failure_preserves_gate_result(
    monkeypatch, caplog, approved
):
    monkeypatch.setattr(gate.settings, "evaluation_run_id", "eval-1")
    monkeypatch.setattr(
        gate.settings, "internal_test_email_allowlist_raw", "internal@example.com"
    )
    findings = (
        []
        if approved
        else [{"rule_code": "brief_coverage", "reason": "Missing ownership."}]
    )
    _stub_response(monkeypatch, {"approved": approved, "findings": findings})

    async def send(event):
        event["review_capture"]["result"]["approved"] = not approved
        raise RuntimeError("sensitive failure details")

    with caplog.at_level("INFO", logger=gate.__name__):
        result = asyncio.run(
            gate.review_components(
                user_request="Design the service.",
                evidence_bundle={},
                resolved_maturity="prototype",
                candidate_records=[],
                telemetry_context={"user_email": "internal@example.com", "send": send},
            )
        )

    assert result["approved"] is approved
    assert result["terminal"] is False
    assert result["findings"] == findings
    assert "RuntimeError" in caplog.text
    assert "sensitive failure details" not in caplog.text
    assert "Design the service" not in caplog.text


@pytest.mark.parametrize("failure", ["incomplete", "shape", "findings"])
def test_malformed_review_cannot_recover_from_unvalidated_findings(failure):
    guarantees = ["audit_and_provenance"]
    rules = gate._rules_for_connections("production", guarantees)
    schema = gate._response_schema(rule_codes=rules)
    payload = _rule_reviews(
        rules, [{"rule_code": "branch_completion", "reason": "Missing outcome."}]
    )
    if failure == "shape":
        payload["unexpected"] = True
    elif failure == "findings":
        payload["rule_reviews"]["invented"] = {
            "satisfied": False,
            "reason": "Invalid.",
            "record_indexes": [],
        }
    result = gate._review_result(
        _response(
            payload,
            finish_reason="max_tokens" if failure == "incomplete" else "end_turn",
        ),
        schema=schema,
        rule_codes=rules,
        records=[{"source": "a", "target": "b"}],
    )
    assert result["terminal"] is True
    assert result["approved"] is False
    assert result["findings"] == []


@pytest.mark.parametrize("guarantee", tuple(TOPOLOGY_PROOF_REQUIREMENTS))
@pytest.mark.parametrize("provider_approved", [False, True])
def test_production_obligations_reject_through_indexed_findings(
    monkeypatch, guarantee, provider_approved
):
    finding = {
        "rule_code": guarantee,
        "reason": "The declared production obligation has no directed runtime path.",
        "record_indexes": [0, 1],
    }
    calls = _stub_response(
        monkeypatch, {"approved": provider_approved, "findings": [finding]}
    )
    result = asyncio.run(
        gate.review_connections(
            user_request="Design the production service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[
                {"source": "input", "target": "accepted"},
                {"source": "input", "target": "rejected"},
            ],
            required_production_guarantees=[guarantee],
        )
    )
    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["findings"] == [finding]
    assert guarantee in result["checked_rules"]
    assert "proofs" not in result
    schema = calls[0]["response_schema"]
    assert set(schema["properties"]) == {"rule_reviews"}
    prompt = calls[0]["messages"][0]["content"]
    requirements = json.loads(
        prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert requirements[guarantee] == STAGED_PRODUCTION_REQUIREMENTS[guarantee]
    assert "production_proofs" not in prompt
    assert "route_witnesses" not in prompt


def test_complete_production_audit_can_approve_without_proof_rows(monkeypatch):
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    guarantees = tuple(TOPOLOGY_PROOF_REQUIREMENTS)
    result = asyncio.run(
        gate.review_connections(
            user_request="Review the production service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[],
            required_production_guarantees=guarantees,
        )
    )
    assert result["approved"] is True
    assert result["terminal"] is False
    assert set(result["checked_rules"]) == set(
        gate._rules_for_connections("production", guarantees)
    )
    assert set(calls[0]["response_schema"]["required"]) == {"rule_reviews"}
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stage", "version_field", "previous_version"),
    [
        ("components", "_COMPONENT_GATE_PROMPT_VERSION", "staged_component_gate_v11"),
        (
            "connections",
            "_CONNECTION_GATE_PROMPT_VERSION",
            "staged_connection_gate_v15",
        ),
    ],
)
def test_per_rule_review_version_invalidates_prior_policy_identity(
    monkeypatch, stage, version_field, previous_version
):
    current_identity = gate.review_identity(stage, "production")
    monkeypatch.setattr(gate, version_field, previous_version)
    assert gate.review_identity(stage, "production") != current_identity


def test_rule_reviews_derive_ordered_failures_and_retain_passing_evidence():
    rules = ("runtime_completeness", "edge_semantics", "safe_action_boundary")
    payload = {
        "rule_reviews": {
            "safe_action_boundary": {
                "satisfied": False,
                "reason": "Approval and recovery outcomes are missing.",
                "record_indexes": [1, 0],
            },
            "edge_semantics": {
                "satisfied": True,
                "reason": "Request and response have distinct directed contracts.",
                "record_indexes": [0, 1],
            },
            "runtime_completeness": {
                "satisfied": False,
                "reason": "No durable outcome is connected.",
                "record_indexes": [],
            },
        }
    }
    result = gate._review_result(
        _response(payload),
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=[{"id": "request"}, {"id": "response"}],
    )
    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["checked_rules"] == list(rules)
    assert result["findings"] == [
        {
            "rule_code": "runtime_completeness",
            "reason": "No durable outcome is connected.",
        },
        {
            "rule_code": "safe_action_boundary",
            "reason": "Approval and recovery outcomes are missing.",
            "record_indexes": [1, 0],
        },
    ]
    assert result["rule_reviews"] == payload["rule_reviews"]
    assert list(result["rule_reviews"]) == list(rules)


def test_numbered_prompt_uses_server_indexes_without_mutating_records(monkeypatch):
    records = [{"id": "n99", "record_index": 450}, {"id": "n2"}]
    calls = _stub_response(monkeypatch, {"approved": True, "findings": []})
    asyncio.run(
        gate.review_components(
            user_request="Review",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=records,
        )
    )
    prompt = calls[0]["messages"][0]["content"]
    numbered = json.loads(
        prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0]
    )
    assert numbered == [
        {"record_index": 0, "record": {"id": "n99", "record_index": 450}},
        {"record_index": 1, "record": {"id": "n2"}},
    ]
    assert "Copy the explicit record_index values" in prompt
    assert "cannot be localized within 32 records" in prompt
    assert records == [{"id": "n99", "record_index": 450}, {"id": "n2"}]


def test_provider_schema_uses_one_strict_uniform_item_for_any_rule_count():
    from adapters.llm_adapter import _anthropic_response_schema

    items = []
    for count in (1, 7, 13):
        codes = tuple(f"rule_{index}" for index in range(count))
        schema = gate._response_schema(rule_codes=codes)
        assert schema["required"] == ["rule_reviews"]
        assert schema["additionalProperties"] is False
        reviews = schema["properties"]["rule_reviews"]
        assert reviews["type"] == "array"
        assert reviews["minItems"] == reviews["maxItems"] == count
        row = reviews["items"]
        assert set(row["required"]) == {
            "rule_code",
            "satisfied",
            "reason",
            "record_indexes",
        }
        assert row["additionalProperties"] is False
        assert row["properties"]["rule_code"]["enum"] == list(codes)
        assert row["properties"]["reason"]["maxLength"] == gate._MAX_REASON_CHARS
        assert (
            row["properties"]["record_indexes"]["maxItems"] == gate._MAX_RECORD_INDEXES
        )
        sanitized = _anthropic_response_schema(schema)
        sanitized_reviews = sanitized["properties"]["rule_reviews"]
        assert (
            "minItems" not in sanitized_reviews and "maxItems" not in sanitized_reviews
        )
        sanitized_item = sanitized_reviews["items"]
        assert sanitized_item["properties"]["rule_code"]["enum"] == list(codes)
        assert "maxLength" not in sanitized_item["properties"]["reason"]
        assert sanitized_item["additionalProperties"] is False
        item_without_codes = json.loads(json.dumps(sanitized_item))
        item_without_codes["properties"]["rule_code"].pop("enum")
        items.append(item_without_codes)
    assert items[0] == items[1] == items[2]


def test_protected_capture_retains_complete_rule_evidence_and_raw_records(monkeypatch):
    monkeypatch.setattr(gate.settings, "evaluation_run_id", "rule-review-eval")
    monkeypatch.setattr(
        gate.settings, "internal_test_email_allowlist_raw", "internal@example.com"
    )
    payload = _rule_reviews(gate.COMPONENT_RULE_CODES)
    payload["rule_reviews"]["objective_fidelity"] = {
        "satisfied": True,
        "reason": "Record 0 owns the requested workflow.",
        "record_indexes": [0],
    }
    _stub_response(monkeypatch, payload)
    events = []

    async def send(event):
        events.append(event)

    records = [{"id": "workflow"}]
    result = asyncio.run(
        gate.review_components(
            user_request="Review",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=records,
            telemetry_context={
                "user_email": "internal@example.com",
                "is_production": False,
                "send": send,
            },
        )
    )
    capture = events[0]["review_capture"]
    assert capture["candidate_records"] == records
    assert capture["result"]["rule_reviews"] == payload["rule_reviews"]
    capture["result"]["rule_reviews"]["objective_fidelity"]["record_indexes"].append(99)
    assert result["rule_reviews"]["objective_fidelity"]["record_indexes"] == [0]


@pytest.mark.parametrize(
    "malformation",
    [
        "missing",
        "extra",
        "duplicate",
        "unknown",
        "non_string",
        "missing_code",
        "null_row",
    ],
)
def test_rule_review_array_requires_every_rule_exactly_once(malformation):
    rules = ("brief_coverage", "objective_fidelity")
    rows = [
        {
            "rule_code": code,
            "satisfied": True,
            "reason": "The owner matches the request.",
            "record_indexes": [],
        }
        for code in rules
    ]
    if malformation == "missing":
        rows.pop()
    elif malformation == "extra":
        rows.append(dict(rows[0]))
    elif malformation == "duplicate":
        rows[1]["rule_code"] = rules[0]
    elif malformation == "unknown":
        rows[1]["rule_code"] = "invented"
    elif malformation == "non_string":
        rows[1]["rule_code"] = [rules[1]]
    elif malformation == "missing_code":
        rows[1].pop("rule_code")
    else:
        rows[1] = None
    result = gate._review_result(
        _response({"rule_reviews": rows}),
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=[],
    )
    assert result["terminal"] is True
    assert result["approved"] is False
    assert result["findings"] == []
    assert "rule_reviews" not in result


def test_previous_keyed_provider_schema_is_rejected():
    rules = ("brief_coverage",)
    response = StructuredLLMResponse(
        text=json.dumps(_rule_reviews(rules)),
        finish_reason="end_turn",
        input_tokens=1,
        output_tokens=1,
        provider="test",
        model="test",
    )
    result = gate._review_result(
        response,
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=[],
    )
    assert result["terminal"] is True
    assert result["approved"] is False
