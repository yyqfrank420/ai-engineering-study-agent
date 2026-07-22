import pytest

from agent.nodes.architecture_workers import _normalise_architect, _worker_context, architect_node


def test_architect_output_becomes_a_bounded_canonical_design_brief():
    brief = _normalise_architect({
        "interpretation": "Turn a terse growth prompt into a bounded campaign optimisation product.",
        "actors": ["Growth lead", "Advertising channel"],
        "inputs": ["Campaign brief", "Conversion events"],
        "outputs": ["Approved campaign changes"],
        "required_capabilities": ["Attribution quality gate", "Bounded channel executor"],
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
    assert brief["assumptions"] == ["Channel APIs support idempotent writes"]
    assert brief["evidence_basis"] == [{
        "claim": "Use an approval gate for large spend changes",
        "basis": "engineering_recommendation",
        "evidence_ref": "write_boundary checklist area",
    }]


def test_challenger_context_audits_the_same_enriched_brief():
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
    assert "Canonical enriched design brief" in context
    assert "Channel write APIs are available" in context


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
