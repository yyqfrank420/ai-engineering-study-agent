import copy
import json
from unittest.mock import AsyncMock

import pytest

from agent import staged_graph_workflow as workflow
from agent.nodes import staged_graph_generation as generation


def _candidate():
    return {
        "title": "Request processing",
        "assumptions": [],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "components": [
            {
                "label": "Request service",
                "type": 101,
                "responsibility": "Processes requests.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"candidate": None, "clarification_questions": []},
        {"candidate": _candidate(), "clarification_questions": ["What is the goal?"]},
        {"candidate": None, "clarification_questions": "What is the goal?"},
        {"candidate": None, "clarification_questions": [None]},
        {"candidate": None, "clarification_questions": [1]},
        {"candidate": None, "clarification_questions": [""]},
        {"candidate": None, "clarification_questions": ["   "]},
        {"candidate": None, "clarification_questions": ["x" * 241]},
        {"candidate": None, "clarification_questions": ["Which workflow?"] * 4},
        {"candidate": None, "clarification_questions": ["What goal?"], "extra": True},
        {"clarification_questions": ["What goal?"]},
    ],
)
def test_component_response_rejects_invalid_clarification(payload):
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_component_response(json.dumps(payload), component_limit=4)


def test_component_response_retains_legacy_candidate_validation():
    candidate = _candidate()
    assert generation._parse_component_response(
        json.dumps({"candidate": candidate, "clarification_questions": []}),
        component_limit=4,
    ) == {
        "wire": generation._parse_component_wire(
            json.dumps(candidate), component_limit=4
        )
    }
    candidate["components"][0]["type"] = 999
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_response(
            json.dumps({"candidate": candidate, "clarification_questions": []}),
            component_limit=4,
        )


def test_component_response_accepts_bounded_trimmed_questions():
    assert generation._parse_component_response(
        json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    " What goal? ",
                    "x" * 240,
                    "Which workflow?",
                ],
            }
        ),
        component_limit=4,
    ) == {"clarification_questions": ["What goal?", "x" * 240, "Which workflow?"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prior_graph",
    [None, {"nodes": [{"id": "prior"}], "edges": [], "title": "Existing graph"}],
)
async def test_create_clarification_uses_one_generation_and_no_downstream_calls(
    monkeypatch, prior_graph
):
    requests = []

    async def component_response(**kwargs):
        requests.append(kwargs)
        return json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    "What business outcome should this system deliver?"
                ],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", component_response)
    downstream = []
    for name in (
        "review_components",
        "review_connections",
        "generate_connection_candidate",
        "_render",
    ):
        boundary = AsyncMock(
            side_effect=AssertionError(f"unexpected downstream call: {name}")
        )
        monkeypatch.setattr(workflow, name, boundary)
        downstream.append(boundary)
    contract = (
        {"maturity": "prototype", "version": "prior-contract"} if prior_graph else None
    )
    state = {
        "request_id": "clarify-request",
        "user_message": "Build an agent for my business.",
        "complexity": "prototype",
        "graph_intent": "create",
        "graph_operation": {
            "kind": "create",
            "status": "candidate",
            "failure_code": None,
        },
        "graph_data": prior_graph,
        "approved_graph_data": prior_graph,
        "graph_contract": contract,
        "approved_graph_contract": contract,
        "evidence_bundle": {},
    }
    before = copy.deepcopy(state)

    result = await workflow.run_staged_graph_pipeline(state)

    assert len(requests) == 1
    assert requests[0]["schema"]["required"] == ["candidate", "clarification_questions"]
    prompt = requests[0]["prompt"]
    assert "business goal or actual workflow is missing" in prompt
    assert "named educational, research, or comparison subject" in prompt
    assert "reasonable stated assumptions suffice" in prompt
    assert all(boundary.await_count == 0 for boundary in downstream)
    assert result["graph_operation"] == {
        "kind": "create",
        "status": "needs_clarification",
        "failure_code": None,
    }
    assert result["clarification_questions"] == [
        "What business outcome should this system deliver?"
    ]
    assert result["graph_changed"] is False
    assert result["graph_publication"] == ("unchanged" if prior_graph else "none")
    assert result["graph_data"] == prior_graph
    assert result["approved_graph_data"] == prior_graph
    assert result["graph_contract"] == contract
    assert result["approved_graph_contract"] == contract
    assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [0, 1])
async def test_scoped_edit_schema_and_parser_reject_clarification(monkeypatch, attempt):
    calls = []

    async def component_response(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"candidate": None, "clarification_questions": ["What goal?"]}
        )

    monkeypatch.setattr(generation, "_run_generation", component_response)
    candidate = _candidate()
    base = {
        **candidate,
        "components": [
            {
                **candidate["components"][0],
                "server_id": "n1",
                "model_index": 0,
                "type": "service",
                "group_kind": "runtime",
            }
        ],
    }
    permissions = {
        "editable_node_fields": {"n1": ["label"]},
        "removable_node_ids": [],
        "allowed_new_node_count": 0,
        "editable_edges": [],
        "editable_edge_fields": {},
        "removable_edge_ids": [],
        "allowed_new_edge_count": 0,
        "added_edge_anchor_node_ids": [],
        "connection_addition_obligations": [],
        "editable_composition_fields": [],
    }

    with pytest.raises(generation.StagedGenerationError, match="schema_invalid"):
        await generation.generate_component_candidate(
            request="Rename Request service to Request processor.",
            resolved_maturity="prototype",
            architecture_context="The service processes requests.",
            write_set=generation.exact_edit_write_set(
                component_ids=["n1"], edge_ids=[]
            ),
            upstream_fingerprint="a" * 64,
            base_components=base,
            edit_permissions=permissions,
            attempt=attempt,
            prior_prompt_fingerprint="b" * 64 if attempt else None,
            prior_write_set_fingerprint=generation._fingerprint(
                generation.exact_edit_write_set(component_ids=["n1"], edge_ids=[])
            )
            if attempt
            else None,
            structural_findings=[
                {"code": "invalid_label", "path": "components", "rule": "label"}
            ]
            if attempt
            else (),
            rejected_candidate=candidate if attempt else None,
        )

    assert len(calls) == 1
    assert "clarification_questions" not in calls[0]["schema"]["properties"]
    assert "clarification_questions" not in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_create_correction_can_clarify_an_invented_business_goal(monkeypatch):
    calls = []
    questions = [
        "Which operational workflow should the agent handle, and what outcome should it achieve?"
    ]

    async def clarify(**kwargs):
        calls.append(kwargs)
        return json.dumps({"candidate": None, "clarification_questions": questions})

    monkeypatch.setattr(generation, "_run_generation", clarify)
    write_set = generation.create_write_set(component_limit=4, edge_limit=6)
    rejected = _candidate()
    rejected["assumptions"] = ["Operations means IT incident response."]

    result = await generation.generate_component_candidate(
        request="Build me an agent for operations.",
        resolved_maturity="prototype",
        architecture_context="Retrieved example: an IT operations agent detects and resolves infrastructure incidents.",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=[
            {"code": "objective_fidelity", "path": "components", "rule": "missing_goal"}
        ],
        rejected_candidate=rejected,
    )

    assert len(calls) == 1
    assert result["clarification_questions"] == questions
    assert "wire" not in result
    prompt = calls[0]["prompt"]
    assert (
        "Retrieved examples cannot choose the user's business domain or goal" in prompt
    )
    assert (
        "Assumptions may fill implementation details but cannot invent a missing business goal or workflow"
        in prompt
    )
    assert (
        "clarification outcome supersedes candidate correction and preservation"
        in prompt
    )
    assert "Return a complete corrected candidate." not in prompt
    criteria = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]
    assert (
        "Retrieved examples cannot choose the user's domain or goal"
        in criteria["objective_fidelity"]
    )
    assert (
        "cannot invent a missing business goal or workflow"
        in criteria["objective_fidelity"]
    )


@pytest.mark.asyncio
async def test_explicit_educational_subject_can_proceed_without_a_business_goal(
    monkeypatch,
):
    calls = []
    candidate = _candidate()
    candidate["title"] = "Retrieval-augmented generation"
    candidate["components"][0]["label"] = "Retrieval pipeline"
    candidate["components"][0]["responsibility"] = (
        "Retrieves evidence and generates a grounded answer."
    )
    candidate["capabilities"]["retrieval_or_reuse"] = True

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps({"candidate": candidate, "clarification_questions": []})

    monkeypatch.setattr(generation, "_run_generation", generate)

    result = await generation.generate_component_candidate(
        request="Explain retrieval-augmented generation and draw its runtime flow.",
        resolved_maturity="prototype",
        architecture_context="Retrieved evidence describes retrieval-augmented generation.",
        write_set=generation.create_write_set(component_limit=4, edge_limit=6),
        upstream_fingerprint="a" * 64,
    )

    assert len(calls) == 1
    assert result["wire"] == candidate
    assert "clarification_questions" not in result
    prompt = calls[0]["prompt"]
    assert (
        "or contrasting paths without inventing an application workflow; proceed with "
        "a candidate for that subject" in prompt
    )
    criteria = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]
    assert (
        "A named educational, research, or comparison subject establishes diagram scope"
        in criteria["objective_fidelity"]
    )


@pytest.mark.parametrize(
    "subject_request",
    [
        "Explain retrieval-augmented generation and draw its runtime flow.",
        "Research current practical trade-offs between agents and fixed workflows "
        "for production AI products.",
        "Compare agentic and fixed workflow paths for an educational diagram.",
    ],
)
def test_named_subject_prompt_preserves_confirmed_diagram_scope(subject_request):
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request=subject_request,
        resolved_maturity="prototype",
        write_set=generation.create_write_set(component_limit=4, edge_limit=6),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Bounded source records.",
    )

    assert "already fulfilling an admitted diagram request" in prompt
    assert "do not ask whether a diagram is wanted" in prompt
    assert prompt.index("A named educational, research, or comparison subject") < (
        prompt.index("For an applied system design")
    )
    assert prompt.index("For an applied system design") < prompt.index(
        "When an applied system's business goal or actual workflow is missing"
    )
    assert "without inventing an application workflow" in prompt
    payload = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert payload["request"] == subject_request
    assert payload["acceptance_criteria"]["objective_fidelity"].startswith(
        "Depict the requested subject"
    )
