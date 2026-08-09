import json

import pytest

from config import settings
from agent.nodes.architecture_workers import (
    _ARCHITECT_PROMPT_VERSION,
    _ARCHITECT_RESPONSE_SCHEMA,
    _ARCHITECT_SYSTEM,
    _CHALLENGER_RESPONSE_SCHEMA,
    _CHALLENGER_SYSTEM,
    _apply_source_backed_plan_locks,
    _is_complete_architect_plan,
    _normalise_architect,
    _normalise_challenger,
    _validate_reviewed_plan_transition,
    _worker_context,
    architect_node,
    challenger_node,
    early_design_frame_node,
    format_diagram_commitments,
)
from agent.stream_utils import StructuredLLMResponse


def _structured_response(
    payload: dict | str,
    *,
    finish_reason: str | None = "end_turn",
) -> StructuredLLMResponse:
    return StructuredLLMResponse(
        text=payload if isinstance(payload, str) else json.dumps(payload),
        finish_reason=finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="anthropic",
        model="claude-opus-5",
    )


def _complete_plan(**overrides):
    return {
        "interpretation": "A bounded production serving platform.",
        "actors": ["Product application", "Platform operator"],
        "inputs": ["Authorized inference request"],
        "outputs": ["Validated model response"],
        "required_capabilities": ["Route one inference request"],
        "diagram_requirements": ["Show the request path and typed failure outcome"],
        "outcome_measures": ["p95 time to first token"],
        "constraints": [],
        "assumptions": ["One self-hosted model is available"],
        "open_questions": ["What is the latency target?"],
        "evidence_basis": [],
        "decisions": [
            {
                "area": "scope",
                "decision": "Ship one inference path first",
                "why": "It satisfies the current request without deferred controls.",
            }
        ],
        "runtime_flow": ["Authorize", "Infer", "Validate", "Return"],
        "status_update": "The reviewed v1 path is ready.",
        **overrides,
    }


def test_architecture_roles_reason_about_enforced_control_paths():
    assert _ARCHITECT_PROMPT_VERSION == "architecture_roles_v17"
    assert "production guarantees as directed paths" in _ARCHITECT_SYSTEM
    assert "timeout-after-commit as an unknown outcome" in _ARCHITECT_SYSTEM
    assert "retrieved content stays untrusted" in _ARCHITECT_SYSTEM
    assert "stable operation identity" in _ARCHITECT_SYSTEM
    assert "complete release/policy" in _ARCHITECT_SYSTEM
    assert "Trace material guarantees through the proposed control topology" in _CHALLENGER_SYSTEM
    assert "observation verification confused with" in _CHALLENGER_SYSTEM
    assert "automatic lanes without an" in _CHALLENGER_SYSTEM
    assert "bounded backpressure and overload" in _ARCHITECT_SYSTEM
    assert "partition/order or event-time semantics" in _ARCHITECT_SYSTEM
    assert "replay/checkpoint and deduplication ownership" in _ARCHITECT_SYSTEM
    assert "compatible schema evolution" in _ARCHITECT_SYSTEM
    assert "complete JSON under 12,000 characters" in _ARCHITECT_SYSTEM
    assert "single downstream design authority" in _CHALLENGER_SYSTEM
    assert "targeted correction audit, not an essay" in _CHALLENGER_SYSTEM
    assert "complete JSON under 12,000 characters" in _CHALLENGER_SYSTEM
    assert "one primary operational scenario" in _ARCHITECT_SYSTEM
    assert "one primary runtime flow starts at the real trigger" in _CHALLENGER_SYSTEM
    assert "authoring, reviewing" in _ARCHITECT_SYSTEM


def test_architecture_worker_schemas_require_every_declared_object_field():
    schemas = (
        _ARCHITECT_RESPONSE_SCHEMA,
        _ARCHITECT_RESPONSE_SCHEMA["properties"]["evidence_basis"]["items"],
        _ARCHITECT_RESPONSE_SCHEMA["properties"]["decisions"]["items"],
        _CHALLENGER_RESPONSE_SCHEMA,
        _CHALLENGER_RESPONSE_SCHEMA["properties"]["accepted_plan"],
        _CHALLENGER_RESPONSE_SCHEMA["properties"]["risks"]["items"],
    )

    for schema in schemas:
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])

    assert "removed_candidate_items" not in _CHALLENGER_RESPONSE_SCHEMA["properties"]
    assert _CHALLENGER_RESPONSE_SCHEMA["properties"]["risks"]["maxItems"] == 5
    assert _CHALLENGER_RESPONSE_SCHEMA["properties"]["tradeoffs"]["maxItems"] == 4


def test_challenger_audit_is_bounded_even_if_a_provider_ignores_the_schema():
    review = _normalise_challenger(
        {
            "accepted_plan": _complete_plan(),
            "risks": [
                {"area": "scope", "risk": f"risk-{index}", "mitigation": "fix"}
                for index in range(8)
            ],
            "missing_requirements": [f"missing-{index}" for index in range(8)],
            "tradeoffs": [f"tradeoff-{index}" for index in range(8)],
            "status_update": "Reviewed.",
        }
    )

    assert len(review["risks"]) == 5
    assert len(review["missing_requirements"]) == 5
    assert len(review["tradeoffs"]) == 4


def test_complete_architect_plan_may_have_no_material_assumptions():
    assert _is_complete_architect_plan({
        "interpretation": "A fully specified evidence explorer.",
        "actors": ["Researcher"],
        "inputs": ["ACL-scoped query"],
        "outputs": ["Cited answer"],
        "required_capabilities": [
            "Authorise evidence scope",
            "Retrieve source passages",
            "Validate claim support",
            "Return cited results",
        ],
        "outcome_measures": ["Supported-claim rate"],
        "assumptions": [],
        "decisions": [
            {"area": "access", "decision": "Enforce source ACLs"},
            {"area": "quality", "decision": "Abstain without support"},
        ],
        "runtime_flow": ["Authorise", "Retrieve", "Validate", "Return"],
    })


def test_architect_output_becomes_a_bounded_canonical_design_brief():
    brief = _normalise_architect({
        "interpretation": "Turn a terse growth prompt into a bounded campaign optimisation product.",
        "actors": ["Growth lead", "Advertising channel"],
        "inputs": ["Campaign brief", "Conversion events"],
        "outputs": ["Approved campaign changes"],
        "required_capabilities": ["Attribution quality gate", "Bounded channel executor"],
        "diagram_requirements": [
            "Route rejected claims back to campaign review",
            "Let analytics-only requests bypass the channel write gate",
        ],
        "outcome_measures": ["Incremental contribution margin"],
        "constraints": ["Constrained objective"],
        "assumptions": ["Channel APIs support idempotent writes"],
        "open_questions": ["Which channels are in scope?"],
        "evidence_basis": [
            {
                "claim": "Use an approval gate for large spend changes",
                "basis": "engineering_recommendation",
                "evidence_ref": "write_boundary checklist area",
            },
            {"claim": "Ignore unsupported provenance", "basis": "invented"},
        ],
        "decisions": [],
        "runtime_flow": ["Validate events", "Propose a bounded change", "Measure outcome"],
    })

    assert brief["actors"] == ["Growth lead", "Advertising channel"]
    assert brief["required_capabilities"] == [
        "Attribution quality gate",
        "Bounded channel executor",
    ]
    assert brief["diagram_requirements"] == [
        "Route rejected claims back to campaign review",
        "Let analytics-only requests bypass the channel write gate",
    ]
    assert brief["assumptions"] == ["Channel APIs support idempotent writes"]
    assert brief["evidence_basis"] == [{
        "claim": "Use an approval gate for large spend changes",
        "basis": "engineering_recommendation",
        "evidence_ref": "write_boundary checklist area",
    }]


@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        (
            {
                "required_capabilities": ["Temperature excursion triage"],
                "decisions": [{"area": "reliability", "decision": "Persist offline alerts", "why": "Intermittent links"}],
            },
            ("Temperature excursion triage", "Persist offline alerts"),
        ),
        (
            {
                "required_capabilities": ["Evidence-linked care guidance"],
                "decisions": [{"area": "safety", "decision": "Escalate uncertain advice to a clinician", "why": "Human accountability"}],
            },
            ("Evidence-linked care guidance", "Escalate uncertain advice to a clinician"),
        ),
        (
            {
                "required_capabilities": ["Reconcile buyer and seller events"],
                "decisions": [{"area": "data", "decision": "Cache versioned catalogue reads", "why": "Bounded latency"}],
            },
            ("Reconcile buyer and seller events", "Cache versioned catalogue reads"),
        ),
    ],
)
def test_out_of_sample_briefs_derive_bounded_diagram_commitments(brief, expected):
    normalised = _normalise_architect({
        "interpretation": "Out-of-sample system",
        "actors": ["Operator"],
        "inputs": ["Validated event"],
        "outputs": ["Observable outcome"],
        "outcome_measures": ["Outcome quality"],
        "assumptions": ["An authoritative source exists"],
        "runtime_flow": ["Accept event", "Return outcome"],
        **brief,
    })

    contract = format_diagram_commitments(normalised)

    assert all(item in contract for item in expected)


def test_challenger_context_ignores_a_stale_architect_brief():
    context = _worker_context(
        {
            "user_message": "expand it",
            "design_query": "growth marketing system expand it",
            "evidence_bundle": {},
            "architect_plan": {
                "interpretation": "Bounded growth optimisation loop",
                "assumptions": ["Channel write APIs are available"],
            },
        },
        "Production depth",
    )

    assert "growth marketing system expand it" in context
    assert "Canonical enriched design brief" not in context
    assert "Channel write APIs are available" not in context


def test_challenger_context_includes_the_primary_plan_for_the_second_pass():
    context = _worker_context(
        {
            "design_query": "growth marketing system",
            "evidence_bundle": {},
        },
        "Production depth",
        primary_plan={"interpretation": "Bounded growth optimisation loop"},
    )

    assert "Primary architect candidate" in context
    assert "Bounded growth optimisation loop" in context


@pytest.mark.asyncio
async def test_architect_failure_stops_graph_input_instead_of_inventing_a_plan(monkeypatch):
    events = []

    async def fail_model(**_kwargs):
        raise TimeoutError("provider timeout")

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        fail_model,
    )
    result = await architect_node({
        "is_applied_design": True,
        "design_query": "customer support chatbot",
        "user_message": "customer support chatbot",
        "complexity": "auto",
        "evidence_bundle": {},
        "send": send,
    })

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_pass_timeout"


@pytest.mark.asyncio
async def test_architect_empty_success_stops_graph_input(monkeypatch):
    captured = {}

    async def empty_model(**kwargs):
        captured.update(kwargs)
        return _structured_response({})

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        empty_model,
    )
    result = await architect_node({
        "is_applied_design": True,
        "design_query": "growth marketing multi-agent system",
        "user_message": "growth marketing multi-agent system",
        "complexity": "auto",
        "evidence_bundle": {},
        "send": send,
    })

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert captured["effort"] == "xhigh"
    assert captured["model"] == settings.architecture_model
    assert captured["timeout_seconds"] == settings.architecture_role_timeout_s
    assert captured["max_output_tokens"] == settings.architecture_max_completion_tokens
    assert captured["response_schema"] is _ARCHITECT_RESPONSE_SCHEMA


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "finish_reason"),
    [
        ("prefix {}", "end_turn"),
        ("{}", "max_tokens"),
        ("{}", None),
    ],
)
async def test_architect_rejects_malformed_or_incomplete_structured_output(
    monkeypatch,
    text,
    finish_reason,
):
    events = []

    async def invalid_model(**_kwargs):
        return _structured_response(text, finish_reason=finish_reason)

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        invalid_model,
    )
    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "customer support chatbot",
            "user_message": "customer support chatbot",
            "complexity": "auto",
            "evidence_bundle": {},
            "send": send,
        }
    )

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_pass_invalid"


@pytest.mark.asyncio
async def test_challenger_failure_stops_graph_input(monkeypatch):
    captured = {}

    async def fail_model(**kwargs):
        captured.update(kwargs)
        raise TimeoutError("provider timeout")

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        fail_model,
    )
    result = await challenger_node({
        "is_applied_design": True,
        "design_query": "airport baggage recovery system",
        "user_message": "airport baggage recovery system",
        "complexity": "production",
        "evidence_bundle": {},
        "architecture_ready": True,
        "architect_plan": {"interpretation": "Airport baggage recovery"},
        "send": send,
    })

    assert result == {"challenger_review": {}, "architecture_ready": False}
    assert captured["effort"] == "medium"
    assert captured["model"] == settings.graph_qa_model
    assert "Primary architect candidate" in captured["messages"][0]["content"]
    assert captured["timeout_seconds"] == settings.architecture_role_timeout_s
    assert captured["max_output_tokens"] == settings.architecture_max_completion_tokens
    assert captured["response_schema"] is _CHALLENGER_RESPONSE_SCHEMA


@pytest.mark.asyncio
async def test_challenger_reports_a_specific_incomplete_plan_code(monkeypatch):
    events = []

    async def incomplete_model(**_kwargs):
        return _structured_response(
            {
                "accepted_plan": _complete_plan(actors=[]),
                "risks": [],
                "missing_requirements": [],
                "tradeoffs": [],
                "status_update": "No complete plan.",
            }
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        incomplete_model,
    )
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design a model-serving stack.",
            "user_message": "Design a model-serving stack.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": _complete_plan(),
            "send": send,
        }
    )

    assert result == {"challenger_review": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_review_incomplete"


@pytest.mark.asyncio
async def test_challenger_replaces_the_candidate_with_one_reviewed_plan(monkeypatch):
    captured = {}
    accepted_plan = _complete_plan(
        constraints=["Run on the user's private GPU cluster"],
        diagram_requirements=[
            "Show the request path and typed failure outcome",
            "Show private-cluster deployment ownership",
        ],
        evidence_basis=[
            {
                "claim": "Deployment stays on the private GPU cluster.",
                "basis": "user",
                "evidence_ref": "private GPU cluster",
            }
        ],
    )

    async def review_model(**kwargs):
        captured.update(kwargs)
        return _structured_response(
            {
                "accepted_plan": accepted_plan,
                "risks": [
                    {
                        "area": "scope",
                        "risk": "The candidate includes a deferred enterprise control plane.",
                        "mitigation": "Keep one versioned release and rollback path in v1.",
                    }
                ],
                "missing_requirements": [],
                "tradeoffs": ["A smaller v1 defers multi-region failover."],
                "status_update": "The oversized control plane was removed.",
            }
        )

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        review_model,
    )
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design a production model-serving stack. Run on the user's private GPU cluster.",
            "user_message": "Design a production model-serving stack. Run on the user's private GPU cluster.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": _complete_plan(
                required_capabilities=[
                    "Route one inference request",
                    "Coordinate multi-region lease fencing and an outbox fleet",
                ],
                constraints=["Run on the user's private GPU cluster"],
                evidence_basis=[
                    {
                        "claim": "Deployment stays on the private GPU cluster.",
                        "basis": "user",
                        "evidence_ref": "private GPU cluster",
                    }
                ],
            ),
            "send": send,
        }
    )

    assert result["architecture_ready"] is True
    assert result["architect_plan"] == accepted_plan
    assert "lease fencing" not in json.dumps(result["architect_plan"])
    assert result["architect_plan"]["constraints"] == [
        "Run on the user's private GPU cluster"
    ]
    assert result["architect_plan"]["evidence_basis"][0]["basis"] == "user"
    assert result["challenger_review"]["risks"][0]["area"] == "scope"
    assert "accepted_plan" not in result["challenger_review"]
    assert "Primary architect candidate" in captured["messages"][0]["content"]


def test_reviewed_plan_can_rewrite_or_remove_architect_generated_content():
    candidate = _complete_plan(
        actors=["Product application", "Invented compliance board"],
        diagram_requirements=["Draw a global control plane"],
        runtime_flow=["Authorize", "Run a global election", "Infer"],
    )
    accepted = _complete_plan(
        actors=["Product application"],
        diagram_requirements=["Show one bounded request path"],
        runtime_flow=["Authorize", "Infer", "Return"],
    )

    reviewed = _apply_source_backed_plan_locks(
        candidate,
        accepted,
        source_request="Design a production model-serving stack.",
    )
    _validate_reviewed_plan_transition(
        reviewed,
        source_request="Design a production model-serving stack.",
    )

    assert reviewed["actors"] == ["Product application"]
    assert reviewed["diagram_requirements"] == ["Show one bounded request path"]
    assert "global election" not in json.dumps(reviewed)


def test_reviewed_plan_locks_verifiable_user_constraints_and_evidence():
    candidate = _complete_plan(
        constraints=["keep all data in region", "Invented GPU requirement"],
        evidence_basis=[
            {
                "claim": "Data residency is required.",
                "basis": "user",
                "evidence_ref": "keep all data in region",
            },
            {
                "claim": "A private GPU is required.",
                "basis": "user",
                "evidence_ref": "invented private GPU",
            },
        ],
    )

    reviewed = _apply_source_backed_plan_locks(
        candidate,
        _complete_plan(),
        source_request="Design the service and keep all data in region.",
    )

    assert reviewed["constraints"] == ["keep all data in region"]
    assert reviewed["evidence_basis"] == [candidate["evidence_basis"][0]]
    _validate_reviewed_plan_transition(
        reviewed,
        source_request="Design the service and keep all data in region.",
    )


def test_reviewed_plan_prefers_corrected_user_evidence_for_the_same_source_quote():
    candidate = _complete_plan(
        evidence_basis=[
            {
                "claim": "Use one fixed region forever.",
                "basis": "user",
                "evidence_ref": "keep all data in region",
            }
        ]
    )
    corrected = {
        "claim": "Keep request data inside the required region.",
        "basis": "user",
        "evidence_ref": "keep all data in region",
    }

    reviewed = _apply_source_backed_plan_locks(
        candidate,
        _complete_plan(evidence_basis=[corrected]),
        source_request="Design the service and keep all data in region.",
    )

    assert reviewed["evidence_basis"] == [corrected]


@pytest.mark.parametrize(
    ("accepted", "code"),
    [
        (
            _complete_plan(constraints=["Invented residency requirement"]),
            "architecture_review_constraint_provenance",
        ),
        (
            _complete_plan(
                evidence_basis=[
                    {
                        "claim": "The user requires a private cluster.",
                        "basis": "user",
                        "evidence_ref": "invented private cluster request",
                    }
                ]
            ),
            "architecture_review_evidence_provenance",
        ),
    ],
)
def test_reviewed_plan_validation_has_specific_provenance_codes(accepted, code):
    with pytest.raises(ValueError) as exc_info:
        _validate_reviewed_plan_transition(
            accepted,
            source_request="Design the service.",
        )

    assert exc_info.value.code == code


@pytest.mark.asyncio
async def test_early_design_frame_uses_only_reviewed_plan_fields():
    events = []

    async def send(event):
        events.append(event)

    result = await early_design_frame_node(
        {
            "is_applied_design": True,
            "architecture_ready": True,
            "architect_plan": {
                "interpretation": "A tenant-safe model serving platform.",
                "assumptions": ["Vendor APIs support idempotency keys."],
                "open_questions": ["Which regions are required?"],
                "diagram_requirements": ["PRIVATE GRAPH REQUIREMENT"],
            },
            "challenger_review": {
                "risks": [
                    {
                        "risk": "Unknown outcomes can cause blind retries.",
                        "mitigation": "Use same-key read-back.",
                    }
                ]
            },
            "graph_data": {
                "nodes": [{"label": "PRIVATE NODE"}],
                "edges": [],
            },
            "send": send,
        }
    )

    text = result["early_response_text"]
    assert "diagram review pending" in text
    assert "tenant-safe model serving" in text
    assert "Unknown outcomes" in text
    assert "same-key read-back" in text
    assert "PRIVATE GRAPH REQUIREMENT" not in text
    assert "PRIVATE NODE" not in text
    assert events == [{"type": "response_delta", "content": text}]


@pytest.mark.asyncio
async def test_early_design_frame_emits_nothing_without_a_ready_applied_design():
    events = []

    async def send(event):
        events.append(event)

    result = await early_design_frame_node(
        {
            "is_applied_design": True,
            "architecture_ready": False,
            "architect_plan": {"interpretation": "Unreviewed plan"},
            "send": send,
        }
    )

    assert result == {"early_response_text": ""}
    assert events == []


@pytest.mark.asyncio
async def test_challenger_reports_truncated_output_separately(monkeypatch):
    events = []

    async def truncated_model(**_kwargs):
        return _structured_response("{}", finish_reason="max_tokens")

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        truncated_model,
    )
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design a production model-serving stack.",
            "user_message": "Design a production model-serving stack.",
            "complexity": "production",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": _complete_plan(),
            "send": send,
        }
    )

    assert result == {"challenger_review": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_review_truncated"
