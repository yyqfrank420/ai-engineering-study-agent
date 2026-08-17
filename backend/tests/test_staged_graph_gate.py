import asyncio
import json

import pytest

from agent.nodes import staged_graph_gate as gate
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


def test_component_gate_uses_one_call_and_strips_bad_indexes(monkeypatch):
    records = [{"id": "a"}, {"id": "b"}]
    calls = _stub_response(
        monkeypatch,
        {
            "approved": False,
            "findings": [
                {
                    "rule_code": "domain_specificity",
                    "reason": "The ownership is generic.",
                    "record_indexes": [0, 9, True],
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
        "proofs": [],
        "diagnostics": ["stripped invalid record indexes at finding row 0"],
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


def test_unknown_rule_is_ignored_with_diagnostic(monkeypatch):
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

    assert result["approved"] is True
    assert result["findings"] == []
    assert result["diagnostics"] == ["ignored unknown finding rule at row 0"]


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


def test_production_proofs_cover_required_guarantees_and_validate_route(monkeypatch):
    calls = _stub_response(
        monkeypatch,
        {
            "approved": True,
            "findings": [],
            "production_proofs": [
                {
                    "guarantee": "audit_and_provenance",
                    "approved": True,
                    "edge_witnesses": [],
                    "route_witnesses": [[0, 1]],
                }
            ],
        },
    )
    result = asyncio.run(
        gate.review_connections(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[
                {"source": "entry", "target": "audit"},
                {"source": "audit", "target": "outcome"},
            ],
            required_production_guarantees=["audit_and_provenance"],
        )
    )

    assert result["approved"] is True
    assert result["proofs"][0]["route_witnesses"] == [[0, 1]]
    assert calls[0]["response_schema"]["required"] == [
        "approved",
        "checked_rules",
        "findings",
        "production_proofs",
    ]
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"]
        == gate._CONNECTION_GATE_PROMPT_VERSION
    )


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


def test_failed_production_proof_is_an_independent_finding(monkeypatch):
    _stub_response(
        monkeypatch,
        {
            "approved": False,
            "findings": [],
            "production_proofs": [
                {
                    "guarantee": "audit_and_provenance",
                    "approved": False,
                    "edge_witnesses": [],
                    "route_witnesses": [],
                }
            ],
        },
    )

    result = asyncio.run(
        gate.review_connections(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[],
            required_production_guarantees=["audit_and_provenance"],
        )
    )

    assert result["findings"] == [
        {
            "rule_code": "audit_and_provenance",
            "reason": "The required production guarantee has no accepted proof.",
        }
    ]


def test_gate_rejects_an_incomplete_rule_audit(monkeypatch):
    async def fake_stream(**_kwargs):
        return _response(
            {
                "approved": True,
                "checked_rules": ["domain_specificity"],
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


@pytest.mark.parametrize(
    "route",
    [[], [0, 0], [1], [0, 1]],
)
def test_invalid_production_witnesses_fail_terminally(monkeypatch, route):
    _stub_response(
        monkeypatch,
        {
            "approved": True,
            "findings": [],
            "production_proofs": [
                {
                    "guarantee": "audit_and_provenance",
                    "approved": True,
                    "edge_witnesses": [],
                    "route_witnesses": [route],
                }
            ],
        },
    )
    result = asyncio.run(
        gate.review_connections(
            user_request="Design a service.",
            evidence_bundle={},
            resolved_maturity="production",
            candidate_records=[{"source": "a", "target": "b"}],
            required_production_guarantees=["audit_and_provenance"],
        )
    )
    assert result["terminal"] is True
