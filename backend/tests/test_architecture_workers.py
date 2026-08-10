import json

import pytest
from agent.architecture_playbook import build_evidence_bundle
from agent.nodes.architecture_workers import (
    _ARCHITECT_PROMPT_VERSION,
    _ARCHITECT_RESPONSE_SCHEMA,
    _ARCHITECT_SYSTEM,
    _CHALLENGER_RESPONSE_SCHEMA,
    _CHALLENGER_SYSTEM,
    _REVIEW_PLAN_LIST_LIMITS,
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
from config import settings


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


def _evidence_bundle() -> dict:
    return build_evidence_bundle(
        {
            "rag_chunks": [
                {
                    "book": "AI Engineering",
                    "chapter": 3,
                    "page_number": 42,
                    "section": "Evaluation",
                    "parent_chunk_id": "ai-eng:p42:pc0",
                    "text": "Measure the system.",
                }
            ],
            "research_context": "- [Current source](https://example.com/current): Evaluation method.",
        }
    )


def _evidence_id(bundle: dict, basis: str) -> str:
    return next(
        item["id"] for item in bundle["evidence_records"] if item["basis"] == basis
    )


def test_architecture_roles_reason_about_enforced_control_paths():
    assert _ARCHITECT_PROMPT_VERSION == "architecture_roles_v22"
    for production_requirement in (
        "At selected production depth only, keep risky customer writes",
        "At selected production depth only, treat production guarantees",
        "At selected production depth only, require alternative delivery",
        "At selected production depth only, persist a stable operation identity",
        "At selected production depth only, require model output",
        "At selected production depth only, distinguish no external business mutation",
        "At selected production depth only, when continuous or event-stream input",
        "At selected production depth only, treat every model and prompt",
    ):
        assert production_requirement in _ARCHITECT_SYSTEM
    assert "retrieved content stays untrusted" in _ARCHITECT_SYSTEM
    assert "stable operation identity" in _ARCHITECT_SYSTEM
    assert "complete release/policy" in _ARCHITECT_SYSTEM
    for production_requirement in (
        "At selected production depth only, check ownership",
        "At selected production depth only, trace material guarantees",
        "At selected production depth only, flag retrieved text",
        "At selected production depth only, flag action attempts",
        "At selected production depth only, flag cache keys",
    ):
        assert production_requirement in _CHALLENGER_SYSTEM
    assert "observation verification confused with" in _CHALLENGER_SYSTEM
    assert "automatic lanes without an" in _CHALLENGER_SYSTEM
    assert "bounded backpressure and overload" in _ARCHITECT_SYSTEM
    assert "partition/order or event-time semantics" in _ARCHITECT_SYSTEM
    assert "replay/checkpoint and deduplication ownership" in _ARCHITECT_SYSTEM
    assert "compatible schema evolution" in _ARCHITECT_SYSTEM
    assert "field and list limits below are the complete response bounds" in (
        _ARCHITECT_SYSTEM
    )
    assert "single downstream design authority" in _CHALLENGER_SYSTEM
    assert "targeted correction audit, not an essay" in _CHALLENGER_SYSTEM
    assert "field and list limits below are the complete response bounds" in (
        _CHALLENGER_SYSTEM
    )
    assert "one primary operational scenario" in _ARCHITECT_SYSTEM
    assert "one primary runtime flow starts at the real trigger" in _CHALLENGER_SYSTEM
    assert "authoring, reviewing" in _ARCHITECT_SYSTEM
    assert "latest user request is the only source" in _ARCHITECT_SYSTEM
    assert "latest user request is the only source" in _CHALLENGER_SYSTEM
    assert "selected depth is authoritative" in _ARCHITECT_SYSTEM
    assert "selected depth is authoritative" in _CHALLENGER_SYSTEM
    assert "At prototype depth, use only prototype criteria" in _ARCHITECT_SYSTEM
    assert "At prototype depth, use only prototype criteria" in _CHALLENGER_SYSTEM
    assert "Hard list limits are inclusive: actors 10; inputs 12" in _ARCHITECT_SYSTEM
    assert "evidence_basis 18; decisions 20; runtime_flow 30" in _ARCHITECT_SYSTEM
    assert "Hard audit list limits are inclusive: risks 5" in _CHALLENGER_SYSTEM
    assert (
        "Hard accepted_plan string limits are inclusive characters"
        in _CHALLENGER_SYSTEM
    )
    assert "exact short source slot" in _ARCHITECT_SYSTEM
    assert "exact short source slot" in _CHALLENGER_SYSTEM


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

    architect_properties = _ARCHITECT_RESPONSE_SCHEMA["properties"]
    reviewed_properties = _CHALLENGER_RESPONSE_SCHEMA["properties"]["accepted_plan"][
        "properties"
    ]
    for field, limit in _REVIEW_PLAN_LIST_LIMITS.items():
        assert architect_properties[field]["maxItems"] == limit
        assert reviewed_properties[field]["maxItems"] == limit

    assert architect_properties["interpretation"]["maxLength"] == 400
    assert architect_properties["actors"]["items"]["maxLength"] == 120
    assert architect_properties["diagram_requirements"]["items"]["maxLength"] == 240
    assert (
        architect_properties["evidence_basis"]["items"]["properties"]["evidence_ref"][
            "maxLength"
        ]
        == 500
    )
    assert (
        architect_properties["decisions"]["items"]["properties"]["why"]["maxLength"]
        == 300
    )
    assert architect_properties["runtime_flow"]["items"]["maxLength"] == 300
    assert architect_properties["status_update"]["maxLength"] == 220
    challenger_properties = _CHALLENGER_RESPONSE_SCHEMA["properties"]
    assert (
        challenger_properties["risks"]["items"]["properties"]["risk"]["maxLength"]
        == 300
    )
    assert challenger_properties["missing_requirements"]["items"]["maxLength"] == 260


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
    assert _is_complete_architect_plan(
        {
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
            "diagram_requirements": ["Show the ACL-scoped retrieval and citation path"],
            "outcome_measures": ["Supported-claim rate"],
            "assumptions": [],
            "decisions": [
                {"area": "access", "decision": "Enforce source ACLs"},
                {"area": "quality", "decision": "Abstain without support"},
            ],
            "runtime_flow": ["Authorise", "Retrieve", "Validate", "Return"],
        }
    )


def test_architect_output_becomes_a_bounded_canonical_design_brief():
    brief = _normalise_architect(
        {
            "interpretation": "Turn a terse growth prompt into a bounded campaign optimisation product.",
            "actors": ["Growth lead", "Advertising channel"],
            "inputs": ["Campaign brief", "Conversion events"],
            "outputs": ["Approved campaign changes"],
            "required_capabilities": [
                "Attribution quality gate",
                "Bounded channel executor",
            ],
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
                    "evidence_ref": "write_boundary",
                },
                {"claim": "Ignore unsupported provenance", "basis": "invented"},
            ],
            "decisions": [],
            "runtime_flow": [
                "Validate events",
                "Propose a bounded change",
                "Measure outcome",
            ],
        }
    )

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
    assert brief["evidence_basis"] == [
        {
            "claim": "Use an approval gate for large spend changes",
            "basis": "engineering_recommendation",
            "evidence_ref": "write_boundary",
        }
    ]


@pytest.mark.parametrize(
    "brief",
    [
        {
            "required_capabilities": ["Temperature excursion triage"],
            "decisions": [
                {
                    "area": "reliability",
                    "decision": "Persist offline alerts",
                    "why": "Intermittent links",
                }
            ],
        },
        {
            "required_capabilities": ["Evidence-linked care guidance"],
            "decisions": [
                {
                    "area": "safety",
                    "decision": "Escalate uncertain advice to a clinician",
                    "why": "Human accountability",
                }
            ],
        },
        {
            "required_capabilities": ["Reconcile buyer and seller events"],
            "decisions": [
                {
                    "area": "data",
                    "decision": "Cache versioned catalogue reads",
                    "why": "Bounded latency",
                }
            ],
        },
    ],
)
def test_out_of_sample_briefs_keep_explicit_diagram_commitments(brief):
    normalised = _normalise_architect(
        {
            "interpretation": "Out-of-sample system",
            "actors": ["Operator"],
            "inputs": ["Validated event"],
            "outputs": ["Observable outcome"],
            "diagram_requirements": ["Show the bounded event-to-outcome path"],
            "outcome_measures": ["Outcome quality"],
            "assumptions": ["An authoritative source exists"],
            "runtime_flow": ["Accept event", "Return outcome"],
            **brief,
        }
    )

    contract = format_diagram_commitments(normalised)

    assert contract == "- Show the bounded event-to-outcome path"


def test_architect_normalization_does_not_derive_diagram_requirements():
    plan = _normalise_architect(
        _complete_plan(
            diagram_requirements=[],
            required_capabilities=["Route one inference request"],
            decisions=[
                {
                    "area": "scope",
                    "decision": "Ship one inference path first",
                    "why": "It satisfies the current request.",
                }
            ],
        )
    )

    assert plan["diagram_requirements"] == []
    assert not _is_complete_architect_plan(plan)


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
    assert "Latest user request" in context
    assert "Design context" in context
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


def test_challenger_context_uses_source_slots_instead_of_canonical_ids():
    bundle = _evidence_bundle()
    canonical_id = _evidence_id(bundle, "book")
    context = _worker_context(
        {
            "design_query": "evaluation service",
            "evidence_bundle": bundle,
        },
        "Prototype depth",
        primary_plan=_complete_plan(
            evidence_basis=[
                {
                    "claim": "Evaluation should be measured.",
                    "basis": "book",
                    "evidence_ref": canonical_id,
                }
            ]
        ),
    )

    assert "source_1" in context
    assert canonical_id not in context


@pytest.mark.asyncio
async def test_architect_failure_stops_graph_input_instead_of_inventing_a_plan(
    monkeypatch,
):
    events = []

    async def fail_model(**_kwargs):
        raise TimeoutError("provider timeout")

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        fail_model,
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
    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "growth marketing multi-agent system",
            "user_message": "growth marketing multi-agent system",
            "complexity": "auto",
            "evidence_bundle": {},
            "send": send,
        }
    )

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert captured["effort"] == "high"
    assert captured["model"] == settings.architecture_model
    assert captured["timeout_seconds"] == settings.architecture_role_timeout_s
    assert captured["max_output_tokens"] == settings.architecture_max_completion_tokens
    assert captured["response_schema"] is _ARCHITECT_RESPONSE_SCHEMA


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "finish_reason", "expected_code"),
    [
        ("prefix {}", "end_turn", "architecture_pass_payload_invalid"),
        ("[]", "end_turn", "architecture_pass_payload_invalid"),
        ("{}", "max_tokens", "architecture_pass_truncated"),
        ("{}", None, "architecture_pass_finish_invalid"),
    ],
)
async def test_architect_rejects_malformed_or_incomplete_structured_output(
    monkeypatch,
    text,
    finish_reason,
    expected_code,
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
    assert events[-1]["failure_code"] == expected_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan", "expected_code"),
    [
        (
            _complete_plan(diagram_requirements=[]),
            "architecture_pass_incomplete",
        ),
        (
            _complete_plan(actors=[f"actor-{index}" for index in range(11)]),
            "architecture_pass_list_limit",
        ),
    ],
)
async def test_architect_rejects_missing_commitments_or_response_limits(
    monkeypatch, plan, expected_code
):
    events = []

    async def model(**_kwargs):
        return _structured_response(plan)

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )

    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "Design a service.",
            "user_message": "Design a service.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "send": send,
        }
    )

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == expected_code


@pytest.mark.asyncio
async def test_architect_accepts_schema_bounded_plan_over_legacy_aggregate_limit(
    monkeypatch,
):
    plan = _complete_plan(
        diagram_requirements=["d" * 240 for _ in range(24)],
        runtime_flow=["r" * 300 for _ in range(30)],
    )
    assert len(json.dumps(plan, separators=(",", ":"))) > 12_000

    async def model(**_kwargs):
        return _structured_response(plan)

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )

    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "Design a service.",
            "user_message": "Design a service.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "send": send,
        }
    )

    assert result["architecture_ready"] is True
    assert result["architect_plan"]["diagram_requirements"] == [
        "d" * 240 for _ in range(24)
    ]


@pytest.mark.asyncio
async def test_architect_resolves_short_source_slots_before_validation_and_storage(
    monkeypatch,
):
    bundle = build_evidence_bundle(
        {
            "rag_chunks": [
                {
                    "book": "AI Engineering",
                    "chapter": chapter,
                    "page_number": page,
                    "section": "Evaluation",
                    "parent_chunk_id": f"ai-eng:p{page}:pc0",
                    "text": text,
                }
                for chapter, page, text in (
                    (10, 473, "Measure the system before release."),
                    (10, 474, "Monitor the released system."),
                )
            ],
            "research_context": (
                "- [Current source](https://example.com/current): "
                "Keep evidence attached to decisions."
            ),
        }
    )
    captured = {}
    plan = _complete_plan(
        evidence_basis=[
            {
                "claim": f"Supported claim {index}.",
                "basis": basis,
                "evidence_ref": f"source_{index}",
            }
            for index, basis in enumerate(("book", "book", "web"), start=1)
        ]
    )

    async def model(**kwargs):
        captured.update(kwargs)
        return _structured_response(plan)

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )
    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "Expand the existing graph.",
            "user_message": "Expand the existing graph.",
            "complexity": "prototype",
            "evidence_bundle": bundle,
            "send": send,
        }
    )

    assert result["architecture_ready"] is True
    assert [
        item["evidence_ref"] for item in result["architect_plan"]["evidence_basis"]
    ] == [item["id"] for item in bundle["evidence_records"]]
    prompt = captured["messages"][0]["content"]
    assert "[source_3] web" in prompt
    assert all(item["id"] not in prompt for item in bundle["evidence_records"])


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
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "airport baggage recovery system",
            "user_message": "airport baggage recovery system",
            "complexity": "production",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": {"interpretation": "Airport baggage recovery"},
            "send": send,
        }
    )

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


@pytest.mark.asyncio
async def test_challenger_resolves_source_slots_and_keeps_canonical_storage(
    monkeypatch,
):
    bundle = _evidence_bundle()
    canonical_ids = [
        _evidence_id(bundle, "book"),
        _evidence_id(bundle, "web"),
    ]
    accepted_plan = _complete_plan(
        evidence_basis=[
            {
                "claim": "Evaluation should be measured.",
                "basis": "book",
                "evidence_ref": "source_1",
            },
            {
                "claim": "Current guidance describes evaluation.",
                "basis": "web",
                "evidence_ref": "source_2",
            },
        ]
    )
    captured = {}

    async def model(**kwargs):
        captured.update(kwargs)
        return _structured_response(
            {
                "accepted_plan": accepted_plan,
                "risks": [],
                "missing_requirements": [],
                "tradeoffs": [],
                "status_update": "Reviewed.",
            }
        )

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design an evaluation service.",
            "user_message": "Design an evaluation service.",
            "complexity": "prototype",
            "evidence_bundle": bundle,
            "architecture_ready": True,
            "architect_plan": _complete_plan(
                evidence_basis=[
                    {
                        "claim": "Evaluation should be measured.",
                        "basis": "book",
                        "evidence_ref": canonical_ids[0],
                    },
                    {
                        "claim": "Current guidance describes evaluation.",
                        "basis": "web",
                        "evidence_ref": canonical_ids[1],
                    },
                ]
            ),
            "send": send,
        }
    )

    assert result["architecture_ready"] is True
    assert [
        item["evidence_ref"] for item in result["architect_plan"]["evidence_basis"]
    ] == canonical_ids
    prompt = captured["messages"][0]["content"]
    assert "source_1" in prompt
    assert "source_2" in prompt
    assert all(canonical_id not in prompt for canonical_id in canonical_ids)


@pytest.mark.asyncio
async def test_challenger_rejects_accepted_plan_exceeding_list_limit(monkeypatch):
    events = []

    async def model(**_kwargs):
        return _structured_response(
            {
                "accepted_plan": _complete_plan(
                    runtime_flow=[f"step-{index}" for index in range(31)],
                ),
                "risks": [],
                "missing_requirements": [],
                "tradeoffs": [],
                "status_update": "Reviewed.",
            }
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )

    result = await challenger_node(
        {
            "is_applied_design": True,
            "user_message": "Design a service.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": _complete_plan(),
            "send": send,
        }
    )

    assert result == {"challenger_review": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_review_invalid"


@pytest.mark.asyncio
async def test_challenger_validates_constraints_against_latest_user_request(
    monkeypatch,
):
    events = []

    async def model(**_kwargs):
        return _structured_response(
            {
                "accepted_plan": _complete_plan(
                    constraints=["keep all data in region"],
                ),
                "risks": [],
                "missing_requirements": [],
                "tradeoffs": [],
                "status_update": "Reviewed.",
            }
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )

    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design a service and keep all data in region.",
            "user_message": "Expand its monitoring.",
            "complexity": "prototype",
            "evidence_bundle": {},
            "architecture_ready": True,
            "architect_plan": _complete_plan(
                constraints=["keep all data in region"],
            ),
            "send": send,
        }
    )

    assert result["architecture_ready"] is True
    assert result["architect_plan"]["constraints"] == []
    assert events[-1]["status"] == "complete"


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


def test_reviewed_plan_accepts_only_server_listed_book_and_web_evidence_ids():
    bundle = _evidence_bundle()
    accepted = _complete_plan(
        evidence_basis=[
            {
                "claim": "Evaluation should be measured.",
                "basis": "book",
                "evidence_ref": _evidence_id(bundle, "book"),
            },
            {
                "claim": "The current source describes an evaluation method.",
                "basis": "web",
                "evidence_ref": _evidence_id(bundle, "web"),
            },
            {
                "claim": "Costly writes need an explicit confirmation path.",
                "basis": "engineering_recommendation",
                "evidence_ref": "write_boundary",
            },
        ]
    )

    _validate_reviewed_plan_transition(
        accepted,
        source_request="Design an evaluation service.",
        evidence_bundle=bundle,
    )


@pytest.mark.parametrize(
    ("basis", "evidence_ref"),
    [
        ("book", "Chapter 3, p.42"),
        ("web", "https://example.com/current"),
        ("web", "web:PRIVATE_SENTINEL"),
    ],
)
def test_reviewed_plan_rejects_display_refs_and_invented_evidence_ids(
    basis, evidence_ref
):
    with pytest.raises(ValueError) as exc_info:
        _validate_reviewed_plan_transition(
            _complete_plan(
                evidence_basis=[
                    {
                        "claim": "Unsupported external claim.",
                        "basis": basis,
                        "evidence_ref": evidence_ref,
                    }
                ]
            ),
            source_request="Design an evaluation service.",
            evidence_bundle=_evidence_bundle(),
        )

    assert exc_info.value.code == "architecture_review_evidence_provenance"
    assert exc_info.value.failure_path == "evidence_basis[0].evidence_ref"
    assert exc_info.value.failure_rule == "unknown_evidence_id"
    assert evidence_ref not in str(exc_info.value)


def test_reviewed_plan_rejects_an_evidence_id_with_the_wrong_basis():
    bundle = _evidence_bundle()
    with pytest.raises(ValueError) as exc_info:
        _validate_reviewed_plan_transition(
            _complete_plan(
                evidence_basis=[
                    {
                        "claim": "Unsupported external claim.",
                        "basis": "web",
                        "evidence_ref": _evidence_id(bundle, "book"),
                    }
                ]
            ),
            source_request="Design an evaluation service.",
            evidence_bundle=bundle,
        )

    assert exc_info.value.code == "architecture_review_evidence_provenance"
    assert exc_info.value.failure_path == "evidence_basis[0].basis"
    assert exc_info.value.failure_rule == "basis_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private_id",
    [
        "book:PRIVATE_SENTINEL",
        "source_99",
        "source_2",
        _evidence_id(_evidence_bundle(), "book"),
    ],
)
async def test_architect_rejects_invalid_model_book_refs_with_safe_coordinates(
    monkeypatch,
    caplog,
    private_id,
):
    events = []
    private_claim = "PRIVATE_CLAIM"

    async def model(**_kwargs):
        return _structured_response(
            _complete_plan(
                evidence_basis=[
                    {
                        "claim": private_claim,
                        "basis": "book",
                        "evidence_ref": private_id,
                    }
                ]
            )
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )
    caplog.set_level("WARNING", logger="agent.nodes.architecture_workers")
    result = await architect_node(
        {
            "is_applied_design": True,
            "design_query": "Design an evaluation service.",
            "user_message": "Design an evaluation service.",
            "complexity": "prototype",
            "evidence_bundle": _evidence_bundle(),
            "send": send,
        }
    )

    assert result == {"architect_plan": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_pass_evidence_provenance"
    assert events[-1]["failure_path"] == "evidence_basis[0].evidence_ref"
    assert events[-1]["failure_rule"] == "invalid_evidence_reference"
    assert private_id not in caplog.text
    assert private_claim not in caplog.text
    assert private_id not in str(events[-1])
    assert private_claim not in str(events[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_basis", "record_basis"),
    [("book", "web"), ("book", "book")],
)
async def test_challenger_rejects_canonical_model_refs_with_safe_coordinates(
    monkeypatch,
    response_basis,
    record_basis,
):
    events = []

    async def model(**_kwargs):
        return _structured_response(
            {
                "accepted_plan": _complete_plan(
                    evidence_basis=[
                        {
                            "claim": "The current source mandates this design.",
                            "basis": response_basis,
                            "evidence_ref": _evidence_id(
                                _evidence_bundle(), record_basis
                            ),
                        }
                    ]
                ),
                "risks": [],
                "missing_requirements": [],
                "tradeoffs": [],
                "status_update": "Reviewed.",
            }
        )

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.architecture_workers.stream_structured_llm",
        model,
    )
    result = await challenger_node(
        {
            "is_applied_design": True,
            "design_query": "Design an evaluation service.",
            "user_message": "Design an evaluation service.",
            "complexity": "prototype",
            "evidence_bundle": _evidence_bundle(),
            "architecture_ready": True,
            "architect_plan": _complete_plan(),
            "send": send,
        }
    )

    assert result == {"challenger_review": {}, "architecture_ready": False}
    assert events[-1]["failure_code"] == "architecture_review_evidence_provenance"
    assert events[-1]["failure_path"] == "evidence_basis[0].evidence_ref"
    assert events[-1]["failure_rule"] == "invalid_evidence_reference"


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
