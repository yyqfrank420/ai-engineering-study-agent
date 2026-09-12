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
    return StructuredLLMResponse(
        text=json.dumps(payload),
        finish_reason=finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="test",
        model="test",
    )


def _stub_response(monkeypatch, payload):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        completed = dict(payload)
        completed.setdefault(
            "checked_rules",
            kwargs["response_schema"]["properties"]["checked_rules"]["items"]["enum"],
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
                    "rule_code": "domain_specificity",
                    "reason": "The ownership is generic.",
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
                "rule_code": "domain_specificity",
                "reason": "The ownership is generic.",
                "record_indexes": [0],
            }
        ],
        "diagnostics": [],
        "review_identity": gate.review_identity("components", "prototype"),
        "checked_rules": list(gate.COMPONENT_RULE_CODES),
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
        "staged_component_gate_v8"
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
    generated_criteria = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])[
        "acceptance_criteria"
    ]
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
    if stage == "components":
        assert (
            "Depict the requested subject system"
            in generated_criteria["objective_fidelity"]
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
            "exclude mechanics used to author this response unless explicitly requested "
            "as runtime features of the subject system"
            in generated_criteria["mece_scope"]
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
            code == "selected_depth"
            and stage == "components"
            and maturity == "production"
        ):
            assert requirement.startswith(RUBRIC_CRITERIA[code][1])
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
    assert result["diagnostics"] == ["unknown finding rule at row 0"]


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


@pytest.mark.parametrize("stage", ["components", "connections"])
def test_rejection_without_findings_is_terminal(monkeypatch, stage):
    _stub_response(monkeypatch, {"approved": False, "findings": []})

    if stage == "components":
        result = asyncio.run(
            gate.review_components(
                user_request="Design a service.",
                evidence_bundle={},
                resolved_maturity="prototype",
                candidate_records=[{"id": "a"}],
            )
        )
    else:
        result = asyncio.run(
            gate.review_connections(
                user_request="Design a service.",
                evidence_bundle={},
                resolved_maturity="prototype",
                candidate_records=[{"source": "a", "target": "b"}],
            )
        )

    assert result["approved"] is False
    assert result["terminal"] is True
    assert result["findings"] == []
    assert result["diagnostics"] == ["provider rejected without blocking findings"]


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
    codes = schema["properties"]["findings"]["items"]["properties"]["rule_code"]["enum"]
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
    codes = schema["properties"]["findings"]["items"]["properties"]["rule_code"]["enum"]

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
        == "staged_connection_gate_v7"
    )
    assert "candidate_context.capabilities" in prompt
    assert "candidate_context.assumptions" in prompt
    assert "candidate component responsibilities" in prompt
    assert "Resolved maturity remains authoritative." in prompt
    assert "a durable telemetry sink is a complete outcome" in prompt


def test_runtime_completeness_allows_observation_only_telemetry_outcome():
    assert RUBRIC_CRITERIA["runtime_completeness"] == (
        "connections",
        "Connect observations and accepted processing to measurable outcomes. Require "
        "decisions and actions only when accepted component responsibilities own them. For "
        "observation-only designs, a durable telemetry sink is a complete outcome.",
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
    codes = schema["properties"]["findings"]["items"]["properties"]["rule_code"]["enum"]

    assert result["approved"] is True
    assert "logical_flow" in codes
    assert "branch_completion" in codes


@pytest.mark.parametrize(
    "invalid_audit", ["missing", "duplicate", "unknown", "invalid"]
)
def test_gate_rejects_an_incomplete_rule_audit(monkeypatch, invalid_audit):
    rules = list(gate.COMPONENT_RULE_CODES)
    if invalid_audit == "missing":
        rules.pop()
    elif invalid_audit == "duplicate":
        rules[-1] = rules[0]
    elif invalid_audit == "unknown":
        rules[-1] = "invented"
    else:
        rules[-1] = None

    async def fake_stream(**_kwargs):
        return _response(
            {
                "approved": True,
                "checked_rules": rules,
                "findings": [],
            }
        )

    monkeypatch.setattr(gate, "stream_structured_llm", fake_stream)
    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["terminal"] is True
    assert result["diagnostics"] == ["provider response has invalid top-level fields"]


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
        == calls[0]["response_schema"]["properties"]["checked_rules"]["items"]["enum"]
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
        monkeypatch.setattr(gate, "_MAX_FINDINGS", gate._MAX_FINDINGS + 1)

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
        (
            "mece_scope",
            "Give each material responsibility one clear owner, remove needless duplicates, and exclude diagram-authoring mechanics from the designed runtime.",
        ),
    ],
)
def test_subject_runtime_policy_invalidates_previous_component_review_identity(
    monkeypatch, maturity, rule, previous_requirement
):
    current_identity = gate.review_identity("components", maturity)

    monkeypatch.setitem(RUBRIC_CRITERIA, rule, ("components", previous_requirement))

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
    assert reviewed_records == records
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


@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize(
    "finding",
    [
        None,
        [],
        {"rule_code": "domain_specificity"},
        {"rule_code": [], "reason": "Malformed rule."},
        {"rule_code": "domain_specificity", "reason": " "},
        {"rule_code": "domain_specificity", "reason": None},
        {"rule_code": "domain_specificity", "reason": "Invalid.", "score": 1},
        *[
            {
                "rule_code": "domain_specificity",
                "reason": "Invalid indexes.",
                "record_indexes": indexes,
            }
            for indexes in (None, "0", [1], [True], [-1], [0] * 33)
        ],
    ],
)
def test_malformed_findings_fail_terminally(monkeypatch, approved, finding):
    _stub_response(monkeypatch, {"approved": approved, "findings": [finding]})

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
    assert result["diagnostics"]
    assert result["review_identity"] == gate.review_identity("components", "prototype")


def test_findings_beyond_limit_cannot_be_dropped(monkeypatch):
    finding = {"rule_code": "domain_specificity", "reason": "A blocking defect."}
    _stub_response(
        monkeypatch,
        {"approved": True, "findings": [finding] * (gate._MAX_FINDINGS + 1)},
    )

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["terminal"] is True
    assert result["diagnostics"] == ["findings exceed the response limit"]


def test_non_string_checked_rule_fails_terminally(monkeypatch):
    rules = list(gate.COMPONENT_RULE_CODES)
    rules[0] = []
    _stub_response(
        monkeypatch,
        {"approved": True, "findings": [], "checked_rules": rules},
    )

    result = asyncio.run(
        gate.review_components(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="prototype",
            candidate_records=[],
        )
    )

    assert result["terminal"] is True
    assert result["diagnostics"] == ["provider response has invalid top-level fields"]


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
                    "domain_specificity"
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
    _stub_response(monkeypatch, {"approved": not terminal, "findings": []})
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
        ("fields", "provider response has invalid top-level fields"),
        ("finding", "unknown finding rule at row 0"),
        ("empty_rejection", "provider rejected without blocking findings"),
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
        payload = {
            "approved": True,
            "checked_rules": kwargs["response_schema"]["properties"]["checked_rules"][
                "items"
            ]["enum"],
            "findings": [],
        }
        if failure == "shape":
            payload["unexpected"] = "private provider text"
        elif failure == "fields":
            payload["checked_rules"] = []
        elif failure == "finding":
            payload["findings"] = [{"rule_code": "unknown", "reason": "Invalid."}]
        elif failure == "empty_rejection":
            payload["approved"] = False
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
        f"finding reason at row 0 truncated to {gate._MAX_REASON_CHARS} characters"
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
        else [{"rule_code": "domain_specificity", "reason": "Missing ownership."}]
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
    payload = {
        "approved": False,
        "checked_rules": list(rules),
        "findings": [{"rule_code": "branch_completion", "reason": "Missing outcome."}],
    }
    if failure == "shape":
        payload["unexpected"] = True
    elif failure == "findings":
        payload["findings"].append({"rule_code": "invented", "reason": "Invalid."})
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
    assert set(schema["properties"]) == {"approved", "checked_rules", "findings"}
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
    assert set(calls[0]["response_schema"]["required"]) == {
        "approved",
        "checked_rules",
        "findings",
    }
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stage", "version_field", "previous_version"),
    [
        ("components", "_COMPONENT_GATE_PROMPT_VERSION", "staged_component_gate_v7"),
        ("connections", "_CONNECTION_GATE_PROMPT_VERSION", "staged_connection_gate_v6"),
    ],
)
def test_simplified_review_version_invalidates_prior_policy_identity(
    monkeypatch, stage, version_field, previous_version
):
    current_identity = gate.review_identity(stage, "production")
    monkeypatch.setattr(gate, version_field, previous_version)
    assert gate.review_identity(stage, "production") != current_identity
