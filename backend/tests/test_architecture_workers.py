import pytest

from agent.nodes.architecture_workers import (
    _ARCHITECT_PROMPT_VERSION,
    _ARCHITECT_SYSTEM,
    _CHALLENGER_SYSTEM,
    _is_complete_architect_plan,
    _normalise_architect,
    _worker_context,
    architect_node,
    challenger_node,
    format_diagram_commitments,
)


def test_architecture_roles_reason_about_enforced_control_paths():
    assert _ARCHITECT_PROMPT_VERSION == "architecture_roles_v11"
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


@pytest.mark.asyncio
async def test_architect_failure_keeps_a_bounded_enriched_contract(monkeypatch):
    async def fail_model(**_kwargs):
        raise TimeoutError("provider timeout")

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.architecture_workers.stream_llm", fail_model)
    result = await architect_node({
        "is_applied_design": True,
        "design_query": "customer support chatbot",
        "user_message": "customer support chatbot",
        "complexity": "auto",
        "evidence_bundle": {},
        "send": send,
    })

    brief = result["architect_plan"]
    assert brief["interpretation"] == "customer support chatbot"
    assert brief["required_capabilities"]
    assert brief["runtime_flow"]
    assert brief["assumptions"]
    assert brief["outputs"] == ["Auditable, policy-compliant advisory result"]
    assert not any(
        "execute external" in capability.lower()
        for capability in brief["required_capabilities"]
    )


@pytest.mark.asyncio
async def test_architect_empty_success_uses_the_bounded_fallback(monkeypatch):
    async def empty_model(**_kwargs):
        return "{}"

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.architecture_workers.stream_llm", empty_model)
    result = await architect_node({
        "is_applied_design": True,
        "design_query": "growth marketing multi-agent system",
        "user_message": "growth marketing multi-agent system",
        "complexity": "auto",
        "evidence_bundle": {},
        "send": send,
    })

    brief = result["architect_plan"]
    assert brief["interpretation"] == "growth marketing multi-agent system"
    assert brief["actors"]
    assert brief["inputs"]
    assert brief["outputs"]
    assert len(brief["required_capabilities"]) >= 4
    assert len(brief["runtime_flow"]) >= 4


@pytest.mark.asyncio
async def test_challenger_failure_keeps_an_independent_risk_review(monkeypatch):
    async def fail_model(**_kwargs):
        raise TimeoutError("provider timeout")

    async def send(_event):
        return None

    monkeypatch.setattr("agent.nodes.architecture_workers.stream_llm", fail_model)
    result = await challenger_node({
        "is_applied_design": True,
        "design_query": "airport baggage recovery system",
        "user_message": "airport baggage recovery system",
        "complexity": "production",
        "evidence_bundle": {},
        "send": send,
    })

    assert result["challenger_review"]["risks"]
