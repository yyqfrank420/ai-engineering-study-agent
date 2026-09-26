import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from agent.nodes import staged_graph_generation as generation
from agent import staged_graph_contract as contract
from agent.stream_utils import StructuredLLMResponse


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.parametrize(
    "connection_key", ["initial_connections", "corrected_connections"]
)
def test_retained_closed_loop_primary_reachability(connection_key):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_closed_loop_34661446928.json"
        ).read_text()
    )
    candidate = fixture["candidate"]
    wire = fixture[connection_key]
    accepted_components = [
        {
            "index": index,
            "is_root": index == candidate["root_index"],
            "primary_flow_member": component["primary_flow_member"],
        }
        for index, component in enumerate(candidate["components"])
    ]
    build = {
        **candidate,
        "request_id": "closed-loop-retained-transit",
        "maturity": "production",
        "source": "test",
        "stage": "connections",
        "components": [
            {
                **component,
                "model_index": index,
                "type": generation.NODE_TYPE_CODES[component["type"]],
                "group_kind": generation.GROUP_KIND_CODES[component["group_kind"]],
            }
            for index, component in enumerate(candidate["components"])
        ],
        "connections": [
            {
                "source_id": str(edge["source_index"]),
                "target_id": str(edge["target_index"]),
                "label": edge["label"],
                "flow": generation.FLOW_CODES[edge["flow"]],
                "sync": generation.SYNC_CODES[edge["sync"]],
            }
            for edge in wire["edges"]
        ],
    }
    assert (
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=accepted_components, edge_limit=30
        )
        == wire
    )
    graph = contract.project_graph_data(build)
    assert len(graph["nodes"]) == 11
    assert len(graph["edges"]) == (
        28 if connection_key == "initial_connections" else 25
    )
    assert [step["nodes"] for step in graph["sequence"]] == [
        ["n1"],
        ["n2"],
        ["n3", "n4", "n6", "n7"],
        ["n5", "n8"],
    ]
    assert [step["step"] for step in graph["sequence"]] == [1, 2, 3, 4]
    assert {node for step in graph["sequence"] for node in step["nodes"]} == {
        f"n{index}" for index in range(1, 9)
    }
    assert (
        contract.project_graph_data(contract.reconstruct_staged_graph_build(graph))
        == graph
    )


def test_retained_offline_evaluation_walkthrough_preserves_authored_graph():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/staged_walkthrough_35640918048.json"
        ).read_text()
    )
    candidate, wire = fixture["candidate"], fixture["connections"]
    accepted_components = [
        {
            "index": index,
            "is_root": index == candidate["root_index"],
            "primary_flow_member": component["primary_flow_member"],
        }
        for index, component in enumerate(candidate["components"])
    ]
    assert (
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=accepted_components, edge_limit=180
        )
        == wire
    )
    build = contract.assign_server_ids(
        {
            **candidate,
            "request_id": "retained-offline-evaluation",
            "maturity": "production",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": generation.NODE_TYPE_CODES[component["type"]],
                    "group_kind": generation.GROUP_KIND_CODES[component["group_kind"]],
                }
                for index, component in enumerate(candidate["components"])
            ],
            "connections": [
                {
                    "source_id": str(edge["source_index"]),
                    "target_id": str(edge["target_index"]),
                    "label": edge["label"],
                    "flow": generation.FLOW_CODES[edge["flow"]],
                    "sync": generation.SYNC_CODES[edge["sync"]],
                }
                for edge in wire["edges"]
            ],
        }
    )
    validated = contract.validate_staged_graph_build(build)
    assert validated["components"] == build["components"]
    assert validated["connections"] == build["connections"]
    assert contract.component_fingerprint(validated) == contract.component_fingerprint(
        build
    )
    assert contract.connection_fingerprint(
        validated
    ) == contract.connection_fingerprint(build)

    graph = contract.project_graph_data(validated)
    assert len(graph["nodes"]) == 18
    assert len(graph["edges"]) == 56
    assert graph["edges"][42]["source"] == "n12"
    assert graph["edges"][42]["target"] == "n13"
    assert graph["edges"][42]["flow"] == "feedback"
    assert graph["edges"][43]["source"] == "n13"
    assert graph["edges"][43]["target"] == "n15"
    assert graph["edges"][43]["flow"] == "feedback"
    assert {node for step in graph["sequence"] for node in step["nodes"]} == {
        component["server_id"]
        for component in build["components"]
        if component["primary_flow_member"]
    }
    reconstructed = contract.reconstruct_staged_graph_build(
        graph, {"capabilities": candidate["capabilities"]}
    )
    assert reconstructed["root_index"] == candidate["root_index"] == 0
    assert reconstructed["components"] == build["components"]
    assert reconstructed["connections"] == build["connections"]
    assert contract.component_fingerprint(
        reconstructed
    ) == contract.component_fingerprint(build)
    assert contract.connection_fingerprint(
        reconstructed
    ) == contract.connection_fingerprint(build)
    assert contract.project_graph_data(reconstructed) == graph


def _write_set() -> dict:
    return generation.create_write_set(component_limit=4, edge_limit=6)


def _component_wire() -> dict:
    return {
        "title": "Request processing",
        "assumptions": ["The caller supplies an authenticated request."],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": True,
            "learning_or_release": False,
        },
        "components": [
            {
                "label": "Request gateway",
                "type": 101,
                "responsibility": "Accepts the request.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
        ],
    }


def _connection_wire() -> dict:
    return {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "requests",
                "flow": 400,
                "sync": 500,
            }
        ]
    }


def _connection_exchanges() -> dict:
    return {
        "exchanges": [{**_connection_wire()["edges"][0], "response_label": "response"}]
    }


def _accepted_context() -> dict:
    return {
        "assumptions": ["The caller supplies an authenticated request."],
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": True,
            "learning_or_release": False,
        },
    }


def _architecture_context() -> str:
    return "Stable review frame:\n- goal: Serve authenticated requests."


def _accepted_components() -> list[dict]:
    return [
        {
            "index": 0,
            "id": "n1",
            "label": "Request gateway",
            "type": 104,
            "responsibility": "Accepts authenticated requests.",
        },
        {
            "index": 1,
            "id": "n2",
            "label": "Request service",
            "type": 101,
            "responsibility": "Processes accepted requests.",
        },
    ]


def _response(payload: dict) -> StructuredLLMResponse:
    if "components" in payload:
        payload = {"candidate": payload, "clarification_questions": []}
    return StructuredLLMResponse(
        text=json.dumps(payload),
        finish_reason="end_turn",
        input_tokens=10,
        output_tokens=10,
        provider="kimi",
        model="kimi-k3",
    )


def test_schemas_are_stage_specific_and_id_free():
    component_schema = generation.component_generation_schema(_write_set())
    connection_schema = generation.connection_generation_schema(_write_set())

    assert "edges" not in component_schema["properties"]
    assert (
        "id" not in component_schema["properties"]["components"]["items"]["properties"]
    )
    assert list(connection_schema["properties"]) == ["edges"]
    assert "components" not in connection_schema["properties"]


def test_schemas_require_nonblank_text_and_canonical_integer_codes():
    component = generation.component_generation_schema(_write_set())["properties"]
    component_record = component["components"]["items"]["properties"]
    connection_record = generation.connection_generation_schema(_write_set())[
        "properties"
    ]["edges"]["items"]["properties"]

    for field in ("title",):
        assert component[field]["minLength"] == 1
    for field in ("label", "responsibility", "group_label"):
        assert component_record[field]["minLength"] == 1
    assert component["assumptions"]["items"]["minLength"] == 1
    assert connection_record["label"]["minLength"] == 1
    assert component_record["type"]["enum"] == list(generation.NODE_TYPE_CODES)
    assert component_record["group_kind"]["enum"] == list(generation.GROUP_KIND_CODES)
    assert connection_record["flow"]["enum"] == list(generation.FLOW_CODES)
    assert connection_record["sync"]["enum"] == list(generation.SYNC_CODES)


def test_provider_schema_uses_authoritative_server_contract_limits():
    component = generation.component_generation_schema(_write_set())["properties"]
    component_record = component["components"]["items"]["properties"]
    connection_record = generation.connection_generation_schema(_write_set())[
        "properties"
    ]["edges"]["items"]["properties"]

    assert component["title"]["maxLength"] == contract.TITLE_MAX_CHARS
    assert (
        component["assumptions"]["items"]["maxLength"] == contract.ASSUMPTION_MAX_CHARS
    )
    assert component["components"]["minItems"] == 1
    assert component["root_index"]["maximum"] == 3
    assert component_record["label"]["maxLength"] == contract.COMPONENT_LABEL_MAX_CHARS
    assert (
        component_record["responsibility"]["maxLength"]
        == contract.COMPONENT_RESPONSIBILITY_MAX_CHARS
    )
    assert (
        component_record["group_label"]["maxLength"] == contract.GROUP_LABEL_MAX_CHARS
    )
    assert (
        connection_record["label"]["maxLength"] == contract.CONNECTION_LABEL_MAX_CHARS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wire", "error"),
    [
        (
            {
                **_component_wire(),
                "components": [{**_component_wire()["components"][0], "label": "  "}],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [{**_component_wire()["components"][0], "type": 999}],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "label": "x" * (contract.COMPONENT_LABEL_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        ({**_component_wire(), "components": []}, "component_wire_invalid"),
        ({**_component_wire(), "root_index": 1}, "component_wire_invalid"),
        (
            {
                **_component_wire(),
                "components": [
                    _component_wire()["components"][0],
                    {
                        **_component_wire()["components"][0],
                        "label": " request gateway ",
                    },
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "title": "x" * (contract.TITLE_MAX_CHARS + 1),
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "assumptions": ["x" * (contract.ASSUMPTION_MAX_CHARS + 1)],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "responsibility": "x"
                        * (contract.COMPONENT_RESPONSIBILITY_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "group_label": "x" * (contract.GROUP_LABEL_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "primary_flow_member": False,
                    }
                ],
            },
            "component_wire_invalid",
        ),
    ],
)
async def test_component_generation_rejects_blank_text_and_unknown_codes(
    monkeypatch, wire, error
):
    async def fake_stream(**_kwargs):
        return _response(wire)

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)

    with pytest.raises(generation.StagedGenerationError, match=error):
        await generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["components", "connections"])
async def test_generation_prompt_uses_selected_prototype_maturity(monkeypatch, stage):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(
            _component_wire() if stage == "components" else _connection_exchanges()
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    state = {"resolved_maturity": "prototype"}
    if stage == "components":
        await generation.generate_component_candidate(
            request="Design a production-grade request path.",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            state=state,
        )
    else:
        await generation.generate_connection_candidate(
            request="Design a production-grade request path.",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=_accepted_components(),
            accepted_context=_accepted_context(),
            state=state,
        )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["resolved_maturity"] == "prototype"
    assert "Use prototype criteria only." in prompt
    assert "Do not add production-only controls" in prompt
    if stage == "components":
        assert prompt_input["architecture_context"] == _architecture_context()
        assert "shared evidence and review frame" in prompt
        assert "Avoid vague group labels such as Runtime, Data, or Operations" in prompt
        assert "an internal adapter to an external API remains internal" in prompt
    else:
        assert prompt_input["architecture_context"] is None
        assert "its reverse response edge with the same flow and sync" in prompt
        assert "Pairing is independent of sync" in prompt
        assert "edge_limit counts expanded edges" in prompt
        assert (
            "Route each supporting branch to a rejoin or observable outcome" in prompt
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("maturity", ["prototype", "production"])
async def test_connection_prompt_carries_authoritative_accepted_context(
    monkeypatch, maturity
):
    from agent.architecture_rubric import STAGED_PRODUCTION_REQUIREMENTS

    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_connection_exchanges())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity=maturity,
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
    )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_connections_v25"
    )
    assert prompt_input["accepted_context"] == _accepted_context()
    assert "streaming_integrity" not in prompt_input["acceptance_criteria"]
    if maturity == "production":
        assert prompt_input["authoring_guidance"] == {
            "streaming_integrity": STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]
        }
        assert "applicable design guidance, not blocking acceptance criteria" in prompt
        assert "check each effect owner separately" in prompt
        assert (
            "trace the exact approved action payload and stable operation identity"
            in prompt
        )
        assert "authorization verdict or incidental reachability alone" in prompt
        assert "declared metric pull with reply is a valid normal input" in prompt
        assert "do not add a redundant push or timer" in prompt
        assert "compensation proposal from its producer" in prompt
        assert (
            "A broad downstream response does not establish upstream submission"
            in prompt
        )
        assert "Each declared compensation producer needs an initiating" in prompt
        assert "check each behavior's initiation separately" in prompt
        assert "its normal input does not initiate rollback" in prompt
        assert "original or applied operation reference or recovery input" in prompt
        assert "Combined contracts may cover both behaviors" in prompt
        assert "explicit autonomous action needs no synthetic incoming edge" in prompt
        assert "When human review or human approval is requested or declared" in prompt
        assert (
            "the exact compensation proposal reaches that human decision boundary "
            "before approval"
        ) in prompt
        assert (
            "the outcome owner invokes it with stable identity and controls" in prompt
        )
        assert "a reply naming retry alone does not invoke it" in prompt
        assert (
            "Keep same-owner actions internal and autonomous pollers autonomous"
            in prompt
        )
        assert "curated hostile traces and offline evaluation before release" in prompt
        assert "each serving target's canary, distinct promotion and rollback" in prompt
        assert "do not invent extra components or capabilities" in prompt
    else:
        assert "authoring_guidance" not in prompt_input
        assert "check each effect owner separately" not in prompt
        assert "Each declared compensation producer needs an initiating" not in prompt
    assert prompt_input["accepted_components"] == [
        {
            "index": 0,
            "label": "Request gateway",
            "type": 104,
            "responsibility": "Accepts authenticated requests.",
            "primary_flow_member": False,
            "is_root": False,
        },
        {
            "index": 1,
            "label": "Request service",
            "type": 101,
            "responsibility": "Processes accepted requests.",
            "primary_flow_member": False,
            "is_root": False,
        },
    ]
    assert "Accepted component types are authoritative" in prompt
    assert (
        "Accepted responsibilities, assumptions, and capabilities are authoritative"
        in prompt
    )
    assert (
        "A durable telemetry/log sink completes observation-only responsibilities"
        in prompt
    )
    assert "connect its trigger to the execution path" in prompt
    assert "storing a recommendation does not execute that action" in prompt


@pytest.mark.parametrize(
    "accepted_context",
    [
        {},
        {"assumptions": [], "capabilities": {}},
        {
            "assumptions": [],
            "capabilities": {
                "external_effects": False,
                "retrieval_or_reuse": True,
                "learning_or_release": "false",
            },
        },
        {
            "assumptions": ["x" * (contract.ASSUMPTION_MAX_CHARS + 1)],
            "capabilities": _accepted_context()["capabilities"],
        },
    ],
)
def test_accepted_context_rejects_malformed_or_unbounded_values(accepted_context):
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_accepted_context"
    ):
        generation._accepted_context(accepted_context)


def test_accepted_context_is_an_immutable_snapshot():
    context = _accepted_context()
    accepted = generation._accepted_context(context)
    context["assumptions"].append("A later mutation must not reach the prompt.")
    context["capabilities"]["external_effects"] = True

    assert accepted.prompt_value() == _accepted_context()


@pytest.mark.parametrize(
    "value",
    [
        "",
        " " * 20,
        "x" * (generation._MAX_ARCHITECTURE_CONTEXT_CHARS + 1),
    ],
)
def test_architecture_context_rejects_empty_or_unbounded_values(value):
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_architecture_context"
    ):
        generation._accepted_architecture_context(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason_length", [900, 2_500])
async def test_correction_prompt_preserves_bounded_reason_and_record_indexes(
    monkeypatch,
    reason_length,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    await generation.generate_component_candidate(
        request="Repair the request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="c" * 64,
        attempt=1,
        prior_prompt_fingerprint="d" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        gate_findings=[
            {
                "code": "domain_specificity",
                "path": "components",
                "rule": "semantic_gate",
                "reason": "x" * reason_length,
                "record_indexes": [0, 2],
            }
        ],
    )

    prompt = calls[0]["messages"][0]["content"]
    findings = json.loads(prompt.split("\nINPUT\n", 1)[1])["findings"]["gate"]
    assert findings == [
        {
            "code": "domain_specificity",
            "path": "components",
            "rule": "semantic_gate",
            "reason": "x" * min(reason_length, generation.MAX_REVIEW_REASON_CHARS),
            "record_indexes": [0, 2],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_seconds", [None, 129.875])
@pytest.mark.parametrize("model", ["kimi-k3", "configured-builder-model"])
async def test_component_generation_uses_configured_model_low_one_attempt_and_safe_telemetry(
    monkeypatch,
    timeout_seconds,
    model,
):
    monkeypatch.setattr(generation.settings, "graph_builder_model", model)
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        state={"user_id": "user-1", "session_id": "thread-1", "is_production": True},
        timeout_seconds=timeout_seconds,
    )

    assert result["wire"] == _component_wire()
    assert len(result["prompt_fingerprint"]) == 64
    assert calls[0]["model"] == model
    assert calls[0]["effort"] == "low"
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["timeout_seconds"] == timeout_seconds
    assert calls[0]["telemetry"]["metadata"]["allocated_timeout_s"] == timeout_seconds
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_components_v28"
    )
    assert "request" not in calls[0]["telemetry"]["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (TimeoutError("deadline expired"), "staged_generation_timeout"),
        (RuntimeError("provider unavailable"), "staged_generation_unavailable"),
    ],
)
async def test_component_generation_distinguishes_timeout_from_provider_failure(
    monkeypatch,
    failure,
    error_code,
):
    async def fake_stream(**kwargs):
        raise failure

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(generation.StagedGenerationError, match=error_code) as raised:
        await generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="production",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            timeout_seconds=129.875,
        )
    assert raised.value.__cause__ is failure


@pytest.mark.asyncio
async def test_component_generation_preserves_outer_cancellation(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()

    async def fake_stream(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    task = asyncio.create_task(
        generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="production",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            timeout_seconds=129.875,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_connection_generation_rejects_unaccepted_endpoint_before_return(
    monkeypatch,
):
    async def fake_stream(**kwargs):
        return _response(
            {
                "exchanges": [
                    {
                        "source_index": 0,
                        "target_index": 9,
                        "label": "bad",
                        "flow": 400,
                        "sync": 500,
                        "response_label": "response",
                    }
                ]
            }
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        await generation.generate_connection_candidate(
            request="Connect accepted components",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=[
                {**_accepted_components()[0], "id": "server-a"},
                {**_accepted_components()[1], "id": "server-b"},
            ],
            accepted_context=_accepted_context(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edges",
    [
        [
            {
                "source_index": 0,
                "target_index": 0,
                "label": "loops",
                "flow": 400,
                "sync": 500,
            }
        ],
        [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "requests",
                "flow": 400,
                "sync": 500,
            },
            {
                "source_index": 0,
                "target_index": 1,
                "label": " REQUESTS ",
                "flow": 400,
                "sync": 500,
            },
        ],
        [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "x" * (contract.CONNECTION_LABEL_MAX_CHARS + 1),
                "flow": 400,
                "sync": 500,
            }
        ],
    ],
)
async def test_connection_generation_rejects_server_invalid_edge_identity(
    monkeypatch, edges
):
    async def fake_stream(**_kwargs):
        return _response(
            {"exchanges": [{**edge, "response_label": "response"} for edge in edges]}
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        await generation.generate_connection_candidate(
            request="Connect accepted components",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=[
                {**_accepted_components()[0], "id": "server-a"},
                {**_accepted_components()[1], "id": "server-b"},
            ],
            accepted_context=_accepted_context(),
        )


@pytest.mark.asyncio
async def test_connection_generation_requires_every_primary_member_from_root(
    monkeypatch,
):
    async def fake_stream(**_kwargs):
        return _response({"exchanges": []})

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_unreachable"
    ):
        await generation.generate_connection_candidate(
            request="Connect accepted components",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=[
                {
                    "index": 0,
                    "id": "server-a",
                    "type": 104,
                    "responsibility": "Accepts authenticated requests.",
                    "primary_flow_member": True,
                    "is_root": True,
                },
                {
                    "index": 1,
                    "id": "server-b",
                    "type": 101,
                    "responsibility": "Processes accepted requests.",
                    "primary_flow_member": True,
                    "is_root": False,
                },
            ],
            accepted_context=_accepted_context(),
        )


@pytest.mark.asyncio
async def test_corrected_attempt_carries_sanitized_findings_and_same_write_set(
    monkeypatch,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    rejected_candidate = _component_wire()
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="c" * 64,
        attempt=1,
        prior_prompt_fingerprint="d" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        structural_findings=[
            {"code": "edge_missing", "path": "components.0", "rule": "required"},
            {"code": "ignore", "path": "<instructions>", "rule": "bad text"},
        ],
        gate_findings=[{"code": "gate_failed", "path": "gate.0", "rule": "approved"}],
        rejected_candidate=rejected_candidate,
    )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert "edge_missing" in prompt
    assert "<instructions>" not in prompt
    assert prompt_input["rejected_candidate"] == rejected_candidate
    assert "complete candidate that failed review" in prompt
    assert result["prompt_fingerprint"] != "d" * 64


@pytest.mark.asyncio
async def test_correction_rejects_changed_write_set_or_identical_prompt(monkeypatch):
    async def fake_stream(**kwargs):
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="correction_write_set_changed"
    ):
        await generation.generate_component_candidate(
            request="request",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="e" * 64,
            attempt=1,
            prior_prompt_fingerprint="f" * 64,
            prior_write_set_fingerprint="0" * 64,
            structural_findings=[{"code": "failed", "path": "wire", "rule": "shape"}],
        )

    write_set = _write_set()
    monkeypatch.setattr(generation, "_fingerprint", lambda _value: "f" * 64)
    with pytest.raises(
        generation.StagedGenerationError, match="identical_correction_prompt"
    ):
        await generation.generate_component_candidate(
            request="request",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=write_set,
            upstream_fingerprint="e" * 64,
            attempt=1,
            prior_prompt_fingerprint="f" * 64,
            prior_write_set_fingerprint="f" * 64,
            structural_findings=[{"code": "failed", "path": "wire", "rule": "shape"}],
        )


def _edit_base() -> dict:
    wire = _component_wire()
    return {
        **wire,
        "components": [
            {
                **wire["components"][0],
                "server_id": "n1",
                "model_index": 0,
                "type": "service",
                "group_kind": "runtime",
            },
            {
                **wire["components"][0],
                "label": "Trace sink",
                "server_id": "n2",
                "model_index": 1,
                "type": "datastore",
                "group_kind": "runtime",
                "primary_flow_member": False,
            },
        ],
    }


def _permissions(**changes) -> dict:
    return {
        "editable_node_fields": {},
        "removable_node_ids": [],
        "allowed_new_node_count": 0,
        "editable_edges": [],
        "editable_edge_fields": {},
        "removable_edge_ids": [],
        "allowed_new_edge_count": 0,
        "added_edge_anchor_node_ids": [],
        "connection_addition_obligations": [],
        "editable_composition_fields": [],
        **changes,
    }


async def _generate_edit(monkeypatch, delta, permissions, **changes):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(delta)

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_component_candidate(
        request="Apply the scoped change.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint=_fingerprint("edit base"),
        base_components=_edit_base(),
        edit_permissions=permissions,
        **changes,
    )
    return result, calls


@pytest.mark.asyncio
async def test_component_edit_adds_only_delta_and_preserves_locked_base(monkeypatch):
    addition = {**_component_wire()["components"][0], "label": "Audit service"}
    result, calls = await _generate_edit(
        monkeypatch,
        {
            "additions": [addition],
            "updates": {},
            "capabilities": _accepted_context()["capabilities"],
        },
        _permissions(allowed_new_node_count=1),
    )
    assert [row["label"] for row in result["wire"]["components"]] == [
        "Request gateway",
        "Trace sink",
        "Audit service",
    ]
    assert result["wire"]["title"] == _edit_base()["title"]
    properties = calls[0]["schema"]["properties"]
    assert set(properties) == {"additions", "updates", "capabilities"}
    assert (
        properties["additions"]["minItems"] == properties["additions"]["maxItems"] == 1
    )
    assert "acceptance_criteria" in calls[0]["prompt"]
    assert "server_id" not in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_component_edit_updates_exact_fields_and_proposes_capabilities(
    monkeypatch,
):
    capabilities = {**_accepted_context()["capabilities"], "external_effects": True}
    result, calls = await _generate_edit(
        monkeypatch,
        {
            "additions": [],
            "updates": {
                "slot_0": {
                    "label": "Ingress",
                    "responsibility": "Accept approved requests.",
                }
            },
            "capabilities": capabilities,
            "title": "New title",
        },
        _permissions(
            editable_node_fields={"n1": ["label", "description"]},
            editable_composition_fields=["title"],
        ),
    )
    assert result["wire"]["components"][0]["label"] == "Ingress"
    assert result["wire"]["components"][1]["label"] == "Trace sink"
    assert result["wire"]["capabilities"] == capabilities
    assert result["wire"]["title"] == "New title"
    assert set(
        calls[0]["schema"]["properties"]["updates"]["properties"]["slot_0"][
            "properties"
        ]
    ) == {"label", "responsibility"}


@pytest.mark.asyncio
async def test_component_edit_removes_server_selected_records(monkeypatch):
    result, _ = await _generate_edit(
        monkeypatch,
        {
            "additions": [],
            "updates": {},
            "capabilities": _accepted_context()["capabilities"],
        },
        _permissions(removable_node_ids=["n2"]),
    )
    assert len(result["wire"]["components"]) == 1
    assert result["wire"]["root_index"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"updates": {"slot_1": {"label": "Other"}}},
        {"updates": {"slot_0": {"label": "Ingress", "type": 102}}},
        {"updates": {"slot_0": {}}},
        {"additions": [_component_wire()["components"][0]]},
        {"title": "Unauthorized title"},
        {"components": []},
    ],
)
async def test_component_delta_rejects_unknown_slots_fields_missing_updates_and_counts(
    monkeypatch, change
):
    delta = {
        "additions": [],
        "updates": {"slot_0": {"label": "Ingress"}},
        "capabilities": _accepted_context()["capabilities"],
        **change,
    }
    with pytest.raises(generation.StagedGenerationError):
        await _generate_edit(
            monkeypatch, delta, _permissions(editable_node_fields={"n1": ["label"]})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "permissions",
    [
        _permissions(editable_node_fields={"n1": ["technology"]}),
        _permissions(editable_node_fields={"missing": ["label"]}),
        _permissions(editable_composition_fields=["sequence"]),
        _permissions(removable_node_ids=["n1"]),
    ],
)
async def test_component_delta_rejects_unrepresentable_authority_before_provider(
    monkeypatch, permissions
):
    async def unexpected(**kwargs):
        pytest.fail("Invalid edit authority reached the provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(generation.StagedGenerationError):
        await generation.generate_component_candidate(
            request="edit",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint=_fingerprint("base"),
            base_components=_edit_base(),
            edit_permissions=permissions,
        )


@pytest.mark.asyncio
async def test_component_correction_projects_rejected_wire_back_to_delta(monkeypatch):
    permissions = _permissions(editable_node_fields={"n1": ["label"]})
    initial = {
        "additions": [],
        "updates": {"slot_0": {"label": "Ingress"}},
        "capabilities": _accepted_context()["capabilities"],
    }
    first, _ = await _generate_edit(monkeypatch, initial, permissions)
    corrected = {**initial, "updates": {"slot_0": {"label": "Request ingress"}}}
    result, calls = await _generate_edit(
        monkeypatch,
        corrected,
        permissions,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        structural_findings=[
            {"code": "label_unclear", "path": "components.0", "rule": "label_unclear"}
        ],
        rejected_candidate=first["wire"],
    )
    prompt_input = json.loads(calls[0]["prompt"].split("\nINPUT\n")[1])
    assert prompt_input["rejected_candidate"] == initial
    assert result["wire"]["components"][0]["label"] == "Request ingress"
    assert "Trace sink" not in json.dumps(prompt_input["rejected_candidate"])


@pytest.mark.asyncio
async def test_connection_delta_matches_original_selector_after_incident_edge_removal(
    monkeypatch,
):
    base = _connection_wire()["edges"]
    permissions = _permissions(
        editable_edges=[
            {"edge_id": "edge_1", "source": "removed", "target": "n1", "label": "old"},
            {"edge_id": "edge_2", "source": "n1", "target": "n2", "label": "requests"},
        ],
        removable_edge_ids=["edge_1"],
        editable_edge_fields={"edge_1": [], "edge_2": ["label", "sync"]},
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1", "n2"],
        connection_addition_obligations=[
            {"source": "n2", "target": "n1", "required_contract": "response"}
        ],
    )
    addition = {**base[0], "source_index": 1, "target_index": 0, "label": "response"}
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "updates": {"slot_0": {"label": "dispatch", "sync": 501}},
                "additions": [addition],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_connection_candidate(
        request="Update the retained request and add a response.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint=_fingerprint("base"),
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        base_connections=base,
        edit_permissions=permissions,
    )
    assert result["wire"]["edges"] == [
        {**base[0], "label": "dispatch", "sync": 501},
        addition,
    ]
    assert "connection_exchanges" not in result
    assert "Propose canonical edges in the delta" in calls[0]["prompt"]
    assert "Propose exchanges only" not in calls[0]["prompt"]
    assert set(
        calls[0]["schema"]["properties"]["additions"]["items"]["properties"]
    ) == {"source_index", "target_index", "label", "flow", "sync"}
    assert "edge_2" not in calls[0]["prompt"]
    assert base == _connection_wire()["edges"]


def test_connection_delta_removal_is_server_owned_and_unknown_selectors_fail():
    base = _connection_wire()["edges"]
    permissions = _permissions(
        editable_edges=[
            {"edge_id": "edge_2", "source": "n1", "target": "n2", "label": "requests"}
        ],
        removable_edge_ids=["edge_2"],
    )
    delta = generation._connection_edit_delta(
        base,
        permissions,
        generation.connection_generation_schema(_write_set()),
        _accepted_components(),
    )
    assert delta.assemble('{"updates":{},"additions":[]}') == {"edges": []}
    with pytest.raises(generation.StagedGenerationError, match="selector"):
        generation._connection_edit_delta(
            base,
            {**permissions, "removable_edge_ids": ["missing"]},
            generation.connection_generation_schema(_write_set()),
            _accepted_components(),
        )


def test_delta_rejects_duplicate_json_slots():
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_json('{"updates":{"slot_0":{},"slot_0":{}},"additions":[]}')


def test_component_delta_removal_reindexes_root_without_reordering_retained_records():
    base = _edit_base()
    base["root_index"] = 1
    base["components"][1]["primary_flow_member"] = True
    delta = generation._component_edit_delta(
        base,
        _permissions(removable_node_ids=["n1"]),
        generation.component_generation_schema(_write_set()),
    )
    wire = delta.assemble(
        json.dumps(
            {"additions": [], "updates": {}, "capabilities": base["capabilities"]}
        )
    )
    assert wire["root_index"] == 0
    assert wire["components"][0]["label"] == "Trace sink"
    assert base["root_index"] == 1
    assert len(base["components"]) == 2


def test_scoped_component_edit_rejects_null_update_and_keeps_original_schema_identity():
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(editable_node_fields={"n1": ["label"]}),
        generation.component_generation_schema(_write_set()),
    )
    response = delta.extract(delta.base)
    assert response["updates"]["slot_0"] == {"label": "Request gateway"}
    assert generation._generation_schema_version("components", delta.schema) == (
        "staged_components_delta_v1"
    )
    response["updates"]["slot_0"] = None
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


@pytest.mark.parametrize(
    "change",
    [
        {"updates": {"slot_1": {"label": "unauthorized"}}},
        {"updates": {"slot_0": {"label": "dispatch", "flow": 401}}},
        {"updates": {}},
        {"updates": {"slot_0": None}},
        {"additions": _connection_wire()["edges"]},
    ],
)
def test_connection_delta_rejects_fields_selectors_missing_updates_and_counts(change):
    permissions = _permissions(
        editable_edges=[
            {"edge_id": "edge_1", "source": "n1", "target": "n2", "label": "requests"}
        ],
        editable_edge_fields={"edge_1": ["label"]},
    )
    delta = generation._connection_edit_delta(
        _connection_wire()["edges"],
        permissions,
        generation.connection_generation_schema(_write_set()),
        _accepted_components(),
    )
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(
            json.dumps(
                {
                    "updates": {"slot_0": {"label": "dispatch"}},
                    "additions": [],
                    **change,
                }
            )
        )


@pytest.mark.parametrize("invalid_code", [101.0, [], {}, True])
def test_scalar_parser_rejects_invalid_code_types(invalid_code):
    wire = _component_wire()
    wire["components"][0]["type"] = invalid_code
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(json.dumps(wire), component_limit=4)


@pytest.mark.asyncio
async def test_recorded_expansion_preserves_attachment_plan_through_both_stages_and_correction(
    monkeypatch,
):
    from pathlib import Path
    from agent.nodes.graph_worker import _user_edit_scope

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_expansion_34649724600.json"
        ).read_text()
    )
    base = contract.reconstruct_staged_graph_build(fixture["base_graph"])
    _, permissions = _user_edit_scope(
        fixture["request"], fixture["base_graph"], resolved_complexity="prototype"
    )
    assert permissions["added_edge_anchor_node_ids"] == ["n6"]
    calls = []
    recorded = fixture["rejected_addition"]
    addition = {
        "label": recorded["label"],
        "type": 101,
        "responsibility": recorded["description"],
        "group_label": "Monitoring",
        "group_kind": 602,
        "primary_flow_member": False,
    }

    async def generate(**kwargs):
        calls.append(kwargs)
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": [addition],
                    "updates": {},
                    "capabilities": base["capabilities"],
                }
            )
        return json.dumps(
            {
                "additions": [
                    {
                        "source_index": 5,
                        "target_index": 8,
                        "label": "monitoring event",
                        "flow": 400,
                        "sync": 501,
                    }
                ],
                "updates": {},
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = generation.exact_edit_write_set(
        component_ids=[f"component_{i}" for i in range(9)],
        edge_ids=[f"edge_{i}" for i in range(15)],
    )
    kwargs = dict(
        request=fixture["request"],
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        base_components=base,
        edit_permissions=permissions,
    )
    first = await generation.generate_component_candidate(**kwargs)
    await generation.generate_component_candidate(
        **kwargs,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=first["wire"],
        gate_findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "mece_scope",
                "reason": "Responsibility requires an unauthorized data-source connection.",
                "record_indexes": [8],
            }
        ],
    )
    prompts = [json.loads(call["prompt"].split("\nINPUT\n")[1]) for call in calls]
    expected = {
        "mode": "attachment",
        "minimum_addition_count": 1,
        "maximum_addition_count": 2,
        "anchor_component_indexes": [5],
        "component_addition_count": 1,
        "enforce_added_edge_contract_label": False,
        "obligations": [
            {
                "source": {"component_index": 5},
                "target": {"addition_index": 0},
                "required_contract": permissions["connection_addition_obligations"][0][
                    "required_contract"
                ],
            }
        ],
    }
    assert (
        prompts[0]["connection_addition_plan"]
        == prompts[1]["connection_addition_plan"]
        == expected
    )
    assert prompts[0]["base"]["components"][5]["label"] == "Metrics Monitor"
    assert prompts[1]["rejected_candidate"]["additions"] == [addition]
    assert (
        "without requiring another data source, dependency, or extra edge"
        in calls[0]["prompt"]
    )
    assert "n6" not in json.dumps(expected)
    assert "When false, required_contract describes intent" in calls[0]["prompt"]
    assert (
        "Never copy edit instructions into a runtime connection label"
        in calls[0]["prompt"]
    )

    accepted = [
        {"id": f"n{index + 1}", "index": index, **row}
        for index, row in enumerate(first["wire"]["components"])
    ]
    await generation.generate_connection_candidate(
        request=fixture["request"],
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="b" * 64,
        accepted_components=accepted,
        accepted_context={key: base[key] for key in ("assumptions", "capabilities")},
        base_connections=[],
        edit_permissions=permissions,
    )
    connection_prompt = json.loads(calls[-1]["prompt"].split("\nINPUT\n")[1])
    assert connection_prompt["connection_addition_plan"] == {
        **expected,
        "accepted_addition_indexes": [8],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"added_edge_anchor_node_ids": ["unknown"]},
        {"added_edge_anchor_node_ids": ["n1", "n1"]},
        {"allowed_new_edge_count": 2},
        {"enforce_added_edge_contract_label": "false"},
        {"allowed_new_node_count": 0},
        {"removable_node_ids": ["n1"]},
        {
            "connection_addition_obligations": [
                {"source": "n1", "target": "$new_node_2", "required_contract": "event"}
            ]
        },
        {
            "connection_addition_obligations": [
                {"source": "n2", "target": "$new_node_1", "required_contract": "event"}
            ]
        },
        {
            "connection_addition_obligations": [
                {
                    "source": "n1",
                    "target": "$new_node_1",
                    "required_contract": "event",
                    "extra": True,
                }
            ]
        },
        {
            "connection_addition_obligations": [
                {
                    "source": "n1",
                    "target": "$new_node_1",
                    "required_contract": "x"
                    * (contract.CONNECTION_LABEL_MAX_CHARS + 1),
                }
            ]
        },
    ],
)
@pytest.mark.asyncio
async def test_invalid_connection_planning_authority_is_rejected_before_component_provider(
    monkeypatch, change
):
    permissions = _permissions(
        allowed_new_node_count=1,
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1"],
        connection_addition_obligations=[
            {"source": "n1", "target": "$new_node_1", "required_contract": "event"}
        ],
    )
    permissions.update(change)

    async def unexpected(**kwargs):
        pytest.fail("Invalid connection authority reached the component provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(generation.StagedGenerationError):
        await generation.generate_component_candidate(
            request="Expand monitoring",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            base_components=_edit_base(),
            edit_permissions=permissions,
        )


@pytest.mark.parametrize("enforce_label", [False, True])
def test_connection_plan_preserves_exact_label_authority_and_contract_owner_limit(
    enforce_label,
):
    from agent.applied_graph_spec import GRAPH_EDGE_LABEL_CHARS

    required_contract = "x" * GRAPH_EDGE_LABEL_CHARS
    permissions = _permissions(
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1", "n2"],
        enforce_added_edge_contract_label=enforce_label,
        connection_addition_obligations=[
            {"source": "n1", "target": "n2", "required_contract": required_contract}
        ],
    )
    plan = generation._connection_addition_plan(permissions, {"n1": 0, "n2": 1})
    assert plan["enforce_added_edge_contract_label"] is enforce_label
    assert plan["obligations"][0]["required_contract"] == required_contract
    permissions["connection_addition_obligations"][0]["required_contract"] += "x"
    with pytest.raises(
        generation.StagedGenerationError, match="edit_connection_plan_invalid"
    ):
        generation._connection_addition_plan(permissions, {"n1": 0, "n2": 1})


def _cold_chain_root_candidate(root_index=5, independent_primary=False):
    # The six primary roles and central root reproduce run 34656915601's upstream chain.
    roles = [
        ("Shipment Sensor Fleet", 106, "Emits identified temperature readings."),
        (
            "Telemetry Ingestion Gateway",
            104,
            "Authenticates and buffers sensor readings.",
        ),
        (
            "Telemetry Normalization Service",
            101,
            "Validates and normalizes sensor readings.",
        ),
        (
            "Excursion Detection Service",
            101,
            "Detects excursions and opens candidate incidents.",
        ),
        ("Incident Event Queue", 103, "Delivers ordered excursion events to triage."),
        (
            "AI Triage & Root-Cause Service",
            101,
            "Classifies excursions and drafts response actions.",
        ),
    ]
    return {
        **_component_wire(),
        "title": "Cold-chain incident processing",
        "root_index": root_index,
        "components": [
            {
                "label": label,
                "type": node_type,
                "responsibility": responsibility,
                "group_label": "Incident runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
            for label, node_type, responsibility in roles
        ]
        + [
            {
                "label": "Independent Incident Reporter",
                "type": 100,
                "responsibility": "Submits separate incident reports to triage.",
                "group_label": "Incident runtime",
                "group_kind": 600,
                "primary_flow_member": independent_primary,
            }
        ],
    }


@pytest.mark.parametrize(("root_index", "independent_primary"), [(5, False), (0, True)])
def test_captured_upstream_chain_requires_initiating_root_and_natural_primary_path(
    root_index, independent_primary
):
    candidate = _cold_chain_root_candidate(root_index, independent_primary)
    connections = {
        "edges": [
            {
                "source_index": index,
                "target_index": index + 1,
                "label": f"Advances incident processing {index}",
                "flow": 400,
                "sync": 501,
            }
            for index in range(5)
        ]
        + [
            {
                "source_index": 6,
                "target_index": 5,
                "label": "Submits an independent incident",
                "flow": 400,
                "sync": 501,
            }
        ]
    }

    def accepted_components(wire):
        return [
            {
                "index": index,
                "is_root": index == wire["root_index"],
                "primary_flow_member": component["primary_flow_member"],
            }
            for index, component in enumerate(wire["components"])
        ]

    def build(wire):
        return contract.assign_server_ids(
            {
                **wire,
                "request_id": "cold-chain-root-replay",
                "maturity": "prototype",
                "source": "test",
                "stage": "connections",
                "components": [
                    {
                        **component,
                        "model_index": index,
                        "type": generation.NODE_TYPE_CODES[component["type"]],
                        "group_kind": generation.GROUP_KIND_CODES[
                            component["group_kind"]
                        ],
                    }
                    for index, component in enumerate(wire["components"])
                ],
                "connections": [
                    {
                        "source_id": str(edge["source_index"]),
                        "target_id": str(edge["target_index"]),
                        "label": edge["label"],
                        "flow": generation.FLOW_CODES[edge["flow"]],
                        "sync": generation.SYNC_CODES[edge["sync"]],
                    }
                    for edge in connections["edges"]
                ],
            }
        )

    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_unreachable"
    ):
        generation._parse_connection_wire(
            json.dumps(connections),
            accepted_components=accepted_components(candidate),
            edge_limit=6,
        )
    with pytest.raises(
        contract.GraphContractError, match="every primary flow member must be reachable"
    ):
        contract.project_graph_data(build(candidate))

    corrected = _cold_chain_root_candidate(root_index=0, independent_primary=False)
    assert (
        generation._parse_connection_wire(
            json.dumps(connections),
            accepted_components=accepted_components(corrected),
            edge_limit=6,
        )
        == connections
    )
    graph = contract.project_graph_data(build(corrected))
    assert len(graph["nodes"]) == 7
    assert len(graph["edges"]) == 6
    assert graph["sequence"][0]["nodes"] == ["n1"]
    assert {edge["source"] + "->" + edge["target"] for edge in graph["edges"]} == {
        "n1->n2",
        "n2->n3",
        "n3->n4",
        "n4->n5",
        "n5->n6",
        "n7->n6",
    }


@pytest.mark.asyncio
async def test_component_generation_receives_root_selection_before_connections(
    monkeypatch,
):
    calls = []
    candidate = _cold_chain_root_candidate(root_index=0)

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps({"candidate": candidate, "clarification_questions": []})

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_component_candidate(
        request="Design cold-chain excursion detection and AI-assisted incident triage.",
        resolved_maturity="prototype",
        architecture_context="Sensor readings initiate excursion detection before AI incident triage.",
        write_set=generation.create_write_set(component_limit=7, edge_limit=6),
        upstream_fingerprint="a" * 64,
    )

    assert result["wire"]["root_index"] == 0
    assert len(calls) == 1
    prompt = calls[0]["prompt"]
    criteria = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]
    root_rule = criteria["objective_fidelity"]
    assert (
        "For new designs, select the initiating primary runtime actor as the root"
        in root_rule
    )
    assert "Every primary member must be naturally reachable outward" in root_rule
    pull_rule = "Determine initiation from declared behavior. A component that pulls or requests data may initiate an outward request with a return response; inbound responses and independent inputs do not disqualify that root. Require contracts consistent with the declared responsibilities, without inventing requests for push-only sources."
    assert pull_rule in root_rule
    assert pull_rule in prompt
    assert (
        "Scoped edits preserve the accepted root and primary membership outside the authorized write set"
        in root_rule
    )


@pytest.mark.parametrize(
    ("primary_members", "edge_contracts", "accepted"),
    [
        ([True, True], [(0, 1, 400), (1, 0, 400)], True),
        ([True, True], [(1, 0, 400)], False),
        ([True, True], [(0, 1, 402), (1, 0, 400)], True),
        ([True, False, True], [(0, 1, 400), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 401), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 402), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 400), (1, 2, 403)], True),
        ([True, False, True], [(1, 0, 400), (1, 2, 400)], False),
        ([True, True], [], False),
    ],
    ids=[
        "pull-request-response",
        "response-only",
        "feedback-request",
        "nonprimary-transit",
        "nonprimary-control-transit",
        "nonprimary-feedback-transit",
        "nonprimary-deployment-transit",
        "nonprimary-reversed-transit",
        "disconnected",
    ],
)
def test_walkthrough_requires_outward_directed_contracts(
    primary_members, edge_contracts, accepted
):
    roles = [
        ("Optimizer", "Initiates optimization by requesting evaluated outcomes."),
        ("Evaluator", "Computes and returns evaluated outcomes for the optimizer."),
        ("Outcome consumer", "Processes evaluated outcomes."),
    ]
    components = [
        {
            **_component_wire()["components"][0],
            "label": label,
            "responsibility": responsibility,
            "primary_flow_member": primary,
        }
        for (label, responsibility), primary in zip(roles, primary_members)
    ]
    edges = [
        {
            "source_index": source,
            "target_index": target,
            "label": "Request evaluated outcomes"
            if source == 0
            else "Return evaluated outcomes",
            "flow": flow,
            "sync": 500,
        }
        for source, target, flow in edge_contracts
    ]
    accepted_components = [
        {"index": index, "is_root": index == 0, "primary_flow_member": primary}
        for index, primary in enumerate(primary_members)
    ]
    build = contract.assign_server_ids(
        {
            **_component_wire(),
            "request_id": "pull-root-regression",
            "maturity": "prototype",
            "source": "test",
            "stage": "connections",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": "service",
                    "group_kind": "runtime",
                }
                for index, component in enumerate(components)
            ],
            "connections": [
                {
                    "source_id": str(edge["source_index"]),
                    "target_id": str(edge["target_index"]),
                    "label": edge["label"],
                    "flow": generation.FLOW_CODES[edge["flow"]],
                    "sync": generation.SYNC_CODES[edge["sync"]],
                }
                for edge in edges
            ],
        }
    )
    if accepted:
        assert generation._parse_connection_wire(
            json.dumps({"edges": edges}),
            accepted_components=accepted_components,
            edge_limit=2,
        ) == {"edges": edges}
        graph = contract.project_graph_data(build)
        assert graph["sequence"][0]["nodes"] == ["n1"]
        assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
            (f"n{source + 1}", f"n{target + 1}") for source, target, _ in edge_contracts
        }
    else:
        with pytest.raises(
            generation.StagedGenerationError, match="connection_wire_unreachable"
        ):
            generation._parse_connection_wire(
                json.dumps({"edges": edges}),
                accepted_components=accepted_components,
                edge_limit=2,
            )
        with pytest.raises(
            contract.GraphContractError,
            match="every primary flow member must be reachable",
        ):
            contract.project_graph_data(build)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_acceptance_is_shared_with_production_only_downstream_guidance(
    maturity,
):
    from agent.architecture_rubric import (
        RUBRIC_CRITERIA,
        STAGED_PRODUCTION_REQUIREMENTS,
        staged_review_requirements,
    )
    from agent.nodes import staged_graph_gate as gate

    request = "Design document automation with feedback-driven prompt releases."
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request=request,
        resolved_maturity=maturity,
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Document processing owns prompt evaluation and release.",
    )
    review_prompt = gate._prompt(
        gate="components",
        user_request=request,
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(),
    )
    generated_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    generated = generated_input["acceptance_criteria"]
    reviewed = json.loads(
        review_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert generated == reviewed == staged_review_requirements("components", maturity)
    assert (
        generated.keys() == staged_review_requirements("components", "prototype").keys()
    )
    feasibility_rule = "At the component stage, assess whether declared responsibilities and assumptions support a feasible directed path; connections are authored in the next stage. Missing edges or absent peer names in responsibilities are not component defects. Identify a specific incompatible responsibility when rejecting root or primary membership; do not demand connection-stage evidence here."
    assert feasibility_rule in generated["objective_fidelity"]
    assert feasibility_rule in reviewed["objective_fidelity"]
    assert "selected_depth" not in generated
    assert RUBRIC_CRITERIA["selected_depth"] == (
        "components",
        "Match component ownership and operational detail to the selected UI depth "
        "without importing deeper criteria.",
    )
    assert {"objective_fidelity", "brief_coverage", "mece_scope"} <= generated.keys()
    if maturity == "prototype":
        assert "downstream_controls" not in generated_input
    else:
        controls = generated_input["downstream_controls"]
        assert controls == STAGED_PRODUCTION_REQUIREMENTS
        assert set(controls).isdisjoint(generated)
        assert all(
            control not in " ".join(generated.values()) for control in controls.values()
        )
        guarantees = contract.production_proofs_for_capabilities(
            {
                "external_effects": True,
                "retrieval_or_reuse": True,
                "learning_or_release": True,
            },
            maturity="production",
        )
        final_requirements = staged_review_requirements(
            "connections", "production", guarantees
        )
        assert "streaming_integrity" not in final_requirements
        assert {
            code: final_requirements[code]
            for code in controls
            if code != "streaming_integrity"
        } == {
            code: guidance
            for code, guidance in controls.items()
            if code != "streaming_integrity"
        }
        assert "downstream_controls" not in review_prompt
        assert (
            "Do not add external effects, retrieval, learning, or streaming solely "
            "to satisfy unrelated guidance"
        ) in prompt
        assert (
            "Connection generation supplies the detailed control contracts and failure "
            "outcomes; it cannot change these component responsibilities"
        ) in prompt


def test_declared_human_authorization_supports_primary_recovery_path():
    components = [
        {
            **_component_wire()["components"][0],
            "label": "Human Decision Console",
            "responsibility": "Issues exact-action authorization after a human decision.",
        },
        {
            **_component_wire()["components"][0],
            "label": "Recovery Workflow",
            "responsibility": "Executes authorized recovery actions and records results.",
        },
    ]
    candidate = {
        **_component_wire(),
        "assumptions": ["Recovery runs only after explicit human authorization."],
        "components": components,
    }
    assert (
        "edges"
        not in generation.component_generation_schema(_write_set())["properties"]
    )
    assert (
        generation._parse_component_wire(json.dumps(candidate), component_limit=2)
        == candidate
    )
    wire = {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "Authorizes exact recovery action",
                "flow": 401,
                "sync": 501,
            }
        ]
    }
    assert (
        generation._parse_connection_wire(
            json.dumps(wire),
            accepted_components=[
                {"index": index, "is_root": index == 0, "primary_flow_member": True}
                for index in range(2)
            ],
            edge_limit=1,
        )
        == wire
    )
    build = contract.assign_server_ids(
        {
            **candidate,
            "request_id": "authorized-recovery-feasibility",
            "maturity": "prototype",
            "source": "test",
            "stage": "connections",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": "service",
                    "group_kind": "runtime",
                }
                for index, component in enumerate(components)
            ],
            "connections": [
                {
                    "source_id": "0",
                    "target_id": "1",
                    "label": "Authorizes exact recovery action",
                    "flow": "control",
                    "sync": "async",
                }
            ],
        }
    )
    graph = contract.project_graph_data(build)
    assert [step["nodes"] for step in graph["sequence"]] == [["n1"], ["n2"]]
    assert graph["edges"][0]["flow"] == "control"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_retained_expansion_delta_schema_admits_request_response_pair_without_baseline_updates(
    count,
):
    from agent.nodes.graph_worker import staged_edit_scope

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/staged_expansion_34663963035.json"
        ).read_text()
    )
    base = contract.reconstruct_staged_graph_build(fixture["base_graph"])
    _, permissions = staged_edit_scope(
        fixture["request"], fixture["base_graph"], resolved_complexity="prototype"
    )
    accepted = [
        {"id": node["id"], "index": index}
        for index, node in enumerate(fixture["initial_candidate"]["nodes"])
    ]
    indexes = {row["id"]: row["index"] for row in accepted}
    base_edges = [
        {
            "source_index": indexes[row["source_id"]],
            "target_index": indexes[row["target_id"]],
            "label": row["label"],
            "flow": next(
                code
                for code, value in generation.FLOW_CODES.items()
                if value == row["flow"]
            ),
            "sync": next(
                code
                for code, value in generation.SYNC_CODES.items()
                if value == row["sync"]
            ),
        }
        for row in base["connections"]
    ]
    delta = generation._connection_edit_delta(
        base_edges,
        permissions,
        generation.connection_generation_schema(
            generation.create_write_set(component_limit=7, edge_limit=10)
        ),
        accepted,
    )
    assert delta.schema["properties"]["additions"]["minItems"] == 1
    assert delta.schema["properties"]["additions"]["maxItems"] == 2
    assert delta.schema["properties"]["updates"]["properties"] == {}
    pair = (
        fixture["initial_connection_delta"]["additions"]
        + fixture["correction_delta"]["additions"]
    )
    payload = json.dumps({"updates": {}, "additions": (pair + pair)[:count]})
    if count not in {1, 2}:
        with pytest.raises(
            generation.StagedGenerationError, match="edit_delta_addition_count"
        ):
            delta.assemble(payload)
    else:
        assembled = delta.assemble(payload)
        assert assembled["edges"][: len(base_edges)] == base_edges
        assert assembled["edges"][len(base_edges) :] == pair[:count]


def _retained_correction(case):
    return json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_corrections_34704850592.json"
        ).read_text()
    )[case]


def _semantic_findings(case):
    # Keep historical captures intact while replaying rules still used by staged review.
    return [
        {
            "code": finding["rule_code"],
            "path": case["stage"],
            "rule": "semantic_gate",
            **{key: value for key, value in finding.items() if key != "rule_code"},
        }
        for finding in case["first_review"]["findings"]
        if finding["rule_code"] != "selected_depth"
    ]


def _marketing_delta(case, findings=None, capacity=20):
    write_set = generation.create_write_set(component_limit=capacity, edge_limit=60)
    return generation._semantic_correction_delta(
        stage="components",
        maturity="production",
        write_set=write_set,
        attempt=1,
        rejected_candidate=case["original_candidate"],
        findings=_semantic_findings(case) if findings is None else findings,
        schema=generation.component_generation_schema(write_set),
    )


def _delta_response(delta):
    return delta.extract(delta.base)


@pytest.mark.asyncio
@pytest.mark.parametrize("change_request", [False, True])
async def test_connection_correction_adds_missing_controls_without_rewriting_witnesses(
    monkeypatch, change_request
):
    request = _connection_wire()["edges"][0]
    response = {
        **request,
        "source_index": request["target_index"],
        "target_index": request["source_index"],
        "label": "Return execution outcome",
    }
    original = {"edges": [request, response]}
    original_snapshot = json.loads(json.dumps(original))
    write_set = generation.create_write_set(component_limit=4, edge_limit=4)
    findings = [
        {
            "code": "safe_action_boundary",
            "path": "connections",
            "rule": "semantic_gate",
            "record_indexes": [0, 1],
            "reason": "A compensating action has no contract.",
        }
    ]
    delta = generation._semantic_correction_delta(
        stage="connections",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=findings,
        schema=generation.connection_generation_schema(write_set),
        accepted_components=_accepted_components(),
        accepted_context=generation._accepted_context(_accepted_context()),
    )
    payload = delta.extract(original)
    assert payload["updates"] == {"slot_0": None, "slot_1": None}
    update_schema = delta.schema["properties"]["updates"]
    assert update_schema["required"] == ["slot_0", "slot_1"]
    for slot in update_schema["properties"].values():
        assert slot["anyOf"][1] == {"type": "null"}
        assert set(slot["anyOf"][0]["required"]) == set(request)
        assert slot["anyOf"][0]["additionalProperties"] is False
    payload["additions"] = [
        {**request, "label": "Apply approved compensation"},
        {**response, "label": "Return compensation outcome"},
    ]
    if change_request:
        payload["updates"]["slot_0"] = {**request, "label": "Apply approved action"}

    async def generate(**kwargs):
        assert kwargs["schema"] == delta.schema
        return json.dumps(payload)

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_connection_candidate(
        request="Preserve the action and add controlled compensation.",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=findings,
        rejected_candidate=original,
    )
    assert result["wire"]["edges"] == [
        payload["updates"]["slot_0"] or request,
        response,
        *payload["additions"],
    ]
    assert delta.extract(result["wire"]) == payload
    assert original == original_snapshot
    assert delta.base == original


@pytest.mark.asyncio
async def test_marketing_semantic_correction_preserves_owners_and_rejects_full_replacement(
    monkeypatch,
):
    case = _retained_correction("applied_domain")
    original = json.loads(json.dumps(case))
    delta = _marketing_delta(case)
    response = _delta_response(delta)
    assert set(response) == {"additions", "updates", "capabilities"}
    assert set(response["updates"]) == {"slot_7", "slot_15"}
    targeted_indexes = {7, 15}
    for index in targeted_indexes:
        response["updates"][f"slot_{index}"] = {
            **case["original_candidate"]["components"][index],
            "responsibility": f"Corrected ownership for component {index}.",
        }
    calls = []
    wire_response = {
        "candidate": case["bad_corrected_candidate"],
        "clarification_questions": [],
    }

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(wire_response)

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = generation.create_write_set(component_limit=20, edge_limit=60)
    kwargs = dict(
        request=case["request"],
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=_semantic_findings(case),
        rejected_candidate=case["original_candidate"],
    )
    with pytest.raises(
        generation.StagedGenerationError, match="staged_generation_schema_invalid"
    ):
        await generation.generate_component_candidate(**kwargs)
    wire_response = {"candidate": response, "clarification_questions": []}
    result = await generation.generate_component_candidate(**kwargs)
    assert len(result["wire"]["components"]) == 17
    unchanged = set(range(17)) - targeted_indexes
    assert len(unchanged) == 15
    for index in unchanged:
        assert (
            result["wire"]["components"][index]
            == case["original_candidate"]["components"][index]
        )
    for field in ("title", "assumptions", "root_index", "capabilities"):
        assert result["wire"][field] == case["original_candidate"][field]
    assert case == original
    metadata = calls[-1]["telemetry"]["metadata"]
    assert metadata["schema_version"] == "staged_components_correction_response_v2"
    prompt = calls[-1]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n")[1])
    assert prompt_input["base"] is None
    assert prompt_input["rejected_candidate"] == case["original_candidate"]
    assert "never return a full replacement or remove records" in prompt
    assert "Cited record indexes define repair scope, not mandatory rewrites" in prompt
    assert (
        "witness records may remain null when additions resolve a missing control"
        in prompt
    )


@pytest.mark.asyncio
async def test_memory_semantic_correction_retains_required_targeted_write(monkeypatch):
    case = _retained_correction("node_followup")
    candidate = case["accepted_components"]
    accepted = [
        {
            "index": index,
            "id": f"n{index + 1}",
            **record,
            "is_root": index == candidate["root_index"],
        }
        for index, record in enumerate(candidate["components"])
    ]
    write_set = generation.create_write_set(component_limit=10, edge_limit=20)
    response = case["bad_corrected_candidate"]
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(response)

    monkeypatch.setattr(generation, "_run_generation", generate)
    kwargs = dict(
        request=case["request"],
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        accepted_context={
            key: candidate[key] for key in ("assumptions", "capabilities")
        },
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=_semantic_findings(case),
        rejected_candidate=case["original_candidate"],
    )
    with pytest.raises(
        generation.StagedGenerationError, match="staged_generation_schema_invalid"
    ):
        await generation.generate_connection_candidate(**kwargs)
    response = {
        "additions": [],
        "updates": {"slot_7": case["original_candidate"]["edges"][7]},
    }
    result = await generation.generate_connection_candidate(**kwargs)
    assert result["wire"] == case["original_candidate"]
    assert len(result["wire"]["edges"]) == 16
    assert "Propose canonical edges in the delta" in calls[-1]["prompt"]
    assert "Propose exchanges only" not in calls[-1]["prompt"]
    assert (
        "response_label"
        not in calls[-1]["schema"]["properties"]["additions"]["items"]["properties"]
    )
    assert "store curated facts" in result["wire"]["edges"][7]["label"]
    assert calls[-1]["schema"]["properties"]["additions"]["maxItems"] == 4
    assert (
        generation._generation_schema_version("connections", calls[-1]["schema"])
        == "staged_connections_delta_v2"
    )


@pytest.mark.parametrize("indexes", [[True], [-1], [17], [1.5], "4", None])
def test_semantic_correction_rejects_invalid_targets(indexes):
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings[0]["record_indexes"] = indexes
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_correction_findings"
    ):
        _marketing_delta(case, findings)


@pytest.mark.parametrize("rule_code", ["invented_rule", "selected_depth"])
def test_semantic_correction_rejects_unknown_or_retired_rule(rule_code):
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings[0]["code"] = rule_code
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_correction_findings"
    ):
        _marketing_delta(case, findings)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_slot",
        "unknown_null_slot",
        "unknown_field",
        "partial_update",
        "missing_slot",
        "removal",
        "metadata",
        "capacity",
    ],
)
def test_semantic_correction_rejects_authority_expansion(mutation):
    case = _retained_correction("applied_domain")
    delta = _marketing_delta(case, capacity=17)
    response = _delta_response(delta)
    if mutation == "unknown_slot":
        response["updates"]["slot_0"] = case["original_candidate"]["components"][0]
    elif mutation == "unknown_null_slot":
        response["updates"]["slot_0"] = None
    elif mutation == "unknown_field":
        response["updates"]["slot_7"] = {
            **case["original_candidate"]["components"][7],
            "invented": True,
        }
    elif mutation == "missing_slot":
        response["updates"].pop("slot_7")
    elif mutation == "partial_update":
        response["updates"]["slot_7"] = {"label": "Incomplete replacement"}
    elif mutation == "removal":
        response["removals"] = [7]
    elif mutation == "metadata":
        response["assumptions"] = []
    else:
        response["additions"] = [case["original_candidate"]["components"][0]]
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


def _recovery_components():
    original = _component_wire()
    original["components"] = [
        {**original["components"][0], "label": f"Owner {index}"} for index in range(3)
    ]
    original["root_index"] = 2
    return original


def _recovery_delta(stage, original, indexes, *, component_limit=4, edge_limit=4):
    write_set = generation.create_write_set(
        component_limit=component_limit, edge_limit=edge_limit
    )
    return generation._semantic_correction_delta(
        stage=stage,
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "mece_scope" if stage == "components" else "edge_semantics",
                "path": stage,
                "rule": "semantic_gate",
                "record_indexes": indexes,
            }
        ],
        schema=(
            generation.component_generation_schema(write_set)
            if stage == "components"
            else generation.connection_generation_schema(write_set)
        ),
        accepted_components=(
            _accepted_components() if stage == "connections" else None
        ),
        accepted_context=(
            generation._accepted_context(_accepted_context())
            if stage == "connections"
            else None
        ),
        recovery_mode=True,
    )


def test_recovery_component_removal_reindexes_root_and_preserves_uncited_records():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0])
    response = {
        "additions": [],
        "updates": {"slot_0": None},
        "capabilities": original["capabilities"],
        "removals": [0],
    }
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["components"] == original["components"][1:]
    assert assembled["root_index"] == 1
    assert assembled["title"] == original["title"]
    assert assembled["assumptions"] == original["assumptions"]
    assert delta.schema["properties"]["removals"]["items"]["enum"] == [0]


@pytest.mark.asyncio
async def test_component_recovery_uses_one_provider_call_and_keeps_output_limit(
    monkeypatch,
):
    original = _recovery_components()
    write_set = generation.create_write_set(component_limit=3, edge_limit=4)
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(
            {
                "candidate": {
                    "additions": [],
                    "updates": {"slot_0": None},
                    "capabilities": original["capabilities"],
                    "removals": [0],
                },
                "clarification_questions": [],
            }
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_component_candidate(
        request="Draw the accepted request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [0],
            }
        ],
        rejected_candidate=original,
        recovery_mode=True,
        max_output_tokens=777,
    )
    assert result["wire"]["components"] == original["components"][1:]
    assert result["wire"]["root_index"] == 1
    assert len(calls) == 1
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["max_output_tokens"] == 777
    assert calls[0]["telemetry"]["metadata"]["correction_attempt"] == 1
    assert calls[0]["telemetry"]["metadata"]["schema_version"] == (
        "staged_components_recovery_response_v1"
    )


def test_recovery_addition_without_removal_cannot_exceed_original_limit():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0], component_limit=3)
    response = {
        "additions": [{**original["components"][0], "label": "Fourth owner"}],
        "updates": {"slot_0": None},
        "capabilities": original["capabilities"],
        "removals": [],
    }
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(
            json.dumps(delta.assemble(json.dumps(response))), component_limit=3
        )


def test_recovery_component_root_selection_uses_original_or_addition_indexes():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0, 2])
    response = {
        "additions": [],
        "updates": {"slot_0": None, "slot_2": None},
        "capabilities": original["capabilities"],
        "removals": [0, 2],
        "root_index": 1,
        "root_addition_index": None,
    }
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["components"] == [original["components"][1]]
    assert assembled["root_index"] == 0
    response["root_index"] = None
    response["root_addition_index"] = 0
    response["additions"] = [
        {**original["components"][0], "label": "Replacement owner"}
    ]
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["root_index"] == 1
    assert assembled["components"] == [
        original["components"][1],
        response["additions"][0],
    ]


@pytest.mark.parametrize(
    "removals,update,error",
    [
        ([0, 0], None, "recovery_removals_invalid"),
        ([1], None, "recovery_removals_invalid"),
        ([True], None, "recovery_removals_invalid"),
        ([0], "changed", "recovery_removal_update_conflict"),
    ],
)
def test_recovery_rejects_invalid_removals(removals, update, error):
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0])
    response = {
        "additions": [],
        "updates": {
            "slot_0": (
                {**original["components"][0], "label": update}
                if update is not None
                else None
            )
        },
        "capabilities": original["capabilities"],
        "removals": removals,
    }
    with pytest.raises(generation.StagedGenerationError, match=error):
        delta.assemble(json.dumps(response))


@pytest.mark.parametrize(
    "root_index,root_addition_index",
    [(None, None), (2, None), (1, 0), (None, 1), (True, None)],
)
def test_recovery_rejects_invalid_root_selection(root_index, root_addition_index):
    original = _recovery_components()
    delta = _recovery_delta("components", original, [2])
    response = {
        "additions": [{**original["components"][2], "label": "New owner"}],
        "updates": {"slot_2": None},
        "capabilities": original["capabilities"],
        "removals": [2],
        "root_index": root_index,
        "root_addition_index": root_addition_index,
    }
    with pytest.raises(generation.StagedGenerationError, match="recovery_root_invalid"):
        delta.assemble(json.dumps(response))


def test_recovery_global_finding_allows_updates_but_no_deletion():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [])
    assert set(delta.schema["properties"]["updates"]["properties"]) == {
        "slot_0",
        "slot_1",
        "slot_2",
    }
    assert delta.schema["properties"]["removals"]["maxItems"] == 0
    response = {
        "additions": [],
        "updates": {f"slot_{index}": None for index in range(3)},
        "title": original["title"],
        "assumptions": original["assumptions"],
        "capabilities": original["capabilities"],
        "root_index": None,
        "root_addition_index": None,
        "removals": [1],
    }
    with pytest.raises(
        generation.StagedGenerationError, match="recovery_removals_invalid"
    ):
        delta.assemble(json.dumps(response))


def test_recovery_mixed_global_and_local_findings_allow_only_local_deletion():
    original = _recovery_components()
    write_set = _write_set()
    delta = generation._semantic_correction_delta(
        stage="components",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [],
            },
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [1],
            },
        ],
        schema=generation.component_generation_schema(write_set),
        recovery_mode=True,
    )
    assert set(delta.schema["properties"]["updates"]["properties"]) == {
        "slot_0",
        "slot_1",
        "slot_2",
    }
    assert delta.schema["properties"]["removals"]["items"]["enum"] == [1]
    assert delta.removal_allowlist == (1,)


@pytest.mark.asyncio
async def test_connection_recovery_removes_only_cited_edge_and_keeps_components(
    monkeypatch,
):
    first = _connection_wire()["edges"][0]
    second = {**first, "source_index": 1, "target_index": 0, "label": "response"}
    original = {"edges": [first, second]}
    write_set = _write_set()
    finding = {
        "code": "edge_semantics",
        "path": "connections",
        "rule": "semantic_gate",
        "record_indexes": [0],
    }
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"additions": [], "updates": {"slot_0": None}, "removals": [0]}
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    accepted = _accepted_components()
    result = await generation.generate_connection_candidate(
        request="Preserve the response path.",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=[finding],
        rejected_candidate=original,
        recovery_mode=True,
    )
    assert result["wire"] == {"edges": [second]}
    assert "connection_exchanges" not in result
    assert accepted == _accepted_components()
    assert calls[0]["schema"]["properties"]["removals"]["items"]["enum"] == [0]
    assert generation._generation_schema_version("connections", calls[0]["schema"]) == (
        "staged_connections_recovery_delta_v1"
    )
    assert calls[0]["attempt"] == 1
    prompt = calls[0]["prompt"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["recovery_mode"] is True
    assert "simplest complete overview of the original request" in prompt
    assert "Connections cannot change the accepted components" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["initial", "edit_write_set", "base", "edit_permissions"],
)
async def test_recovery_mode_rejects_noncreation_authority(monkeypatch, invalid):
    async def generate(**_kwargs):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(generation, "_run_generation", generate)
    kwargs = dict(
        request="Draw a request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=1,
        recovery_mode=True,
    )
    if invalid == "initial":
        kwargs["attempt"] = 0
    elif invalid == "edit_write_set":
        kwargs["write_set"] = generation.exact_edit_write_set(
            component_ids=["n1"], edge_ids=[]
        )
    elif invalid == "base":
        kwargs["base_components"] = _component_wire()
    else:
        kwargs["edit_permissions"] = {}
    with pytest.raises(generation.StagedGenerationError, match="invalid_recovery_mode"):
        await generation.generate_component_candidate(**kwargs)


@pytest.mark.asyncio
async def test_recovery_structural_correction_keeps_complete_candidate_and_call_limit(
    monkeypatch,
):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"candidate": _component_wire(), "clarification_questions": []}
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = _write_set()
    result = await generation.generate_component_candidate(
        request="Draw a request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=[
            {"code": "component_wire_invalid", "path": "components", "rule": "shape"}
        ],
        rejected_candidate=_component_wire(),
        recovery_mode=True,
    )
    assert result["wire"] == _component_wire()
    assert len(calls) == 1
    assert calls[0]["attempt"] == 1
    assert (
        calls[0]["schema"]["properties"]["candidate"]["anyOf"][0]["properties"].keys()
        == _component_wire().keys()
    )
    prompt_input = json.loads(calls[0]["prompt"].split("\nINPUT\n", 1)[1])
    assert prompt_input["recovery_mode"] is True
    assert "correction_slots" not in prompt_input


def test_indexless_finding_in_mixed_list_grants_global_updates_without_deletion():
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings.append(
        {"code": "objective_fidelity", "path": "components", "rule": "semantic_gate"}
    )
    delta = _marketing_delta(case, findings, capacity=18)
    response = _delta_response(delta)
    assert len(response["updates"]) == 17
    assert set(response) == {
        "updates",
        "additions",
        "title",
        "assumptions",
        "root_index",
        "capabilities",
    }
    addition = {
        **case["original_candidate"]["components"][0],
        "label": "New initiating actor",
    }
    response["additions"] = [addition]
    response["root_index"] = 17
    response["assumptions"] = ["Explicitly corrected global context."]
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=18
    )
    assert assembled["components"][:17] == case["original_candidate"]["components"]
    assert assembled["components"][17] == addition
    assert assembled["root_index"] == 17
    assert assembled["assumptions"] == response["assumptions"]


@pytest.mark.parametrize(
    "code,metadata",
    [
        ("objective_fidelity", {"title", "assumptions", "root_index"}),
        ("capability_classification", {"capabilities"}),
    ],
)
def test_targeted_global_criterion_has_explicit_metadata_scope(code, metadata):
    case = _retained_correction("applied_domain")
    findings = [
        {
            "code": code,
            "path": "components",
            "rule": "semantic_gate",
            "record_indexes": [4],
        }
    ]
    delta = _marketing_delta(case, findings)
    assert (
        set(delta.schema["properties"])
        == {"updates", "additions", "capabilities"} | metadata
    )
    assert set(delta.schema["properties"]["updates"]["properties"]) == {"slot_4"}


@pytest.mark.asyncio
async def test_semantic_component_correction_can_still_clarify(monkeypatch):
    case = _retained_correction("applied_domain")

    async def generate(**kwargs):
        return json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    "Which business workflow should this automate?"
                ],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = generation.create_write_set(component_limit=20, edge_limit=60)
    result = await generation.generate_component_candidate(
        request="Build an operations agent",
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=case["original_candidate"],
        structural_findings=[
            {
                "code": "objective_fidelity",
                "path": "components",
                "rule": "semantic_gate",
            }
        ],
    )
    assert result["clarification_questions"] == [
        "Which business workflow should this automate?"
    ]


def test_component_correction_added_owner_can_change_capabilities():
    original = _component_wire()
    write_set = _write_set()
    delta = generation._semantic_correction_delta(
        stage="components",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "brief_coverage",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [0],
            }
        ],
        schema=generation.component_generation_schema(write_set),
    )
    response = _delta_response(delta)
    assert response["updates"] == {"slot_0": None}
    response["additions"] = [
        {
            **original["components"][0],
            "label": "Approved publication service",
            "responsibility": "Publishes approved changes to the external destination.",
        }
    ]
    response["capabilities"]["external_effects"] = True
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["capabilities"]["external_effects"] is True
    assert assembled["components"][0] == original["components"][0]
    assert original["capabilities"]["external_effects"] is False


def test_create_exchange_schema_keeps_canonical_edges_unchanged():
    canonical = generation.connection_generation_schema(_write_set())
    original = json.loads(json.dumps(canonical))
    schema = generation._connection_create_response_schema(canonical)
    assert canonical == original
    assert schema["required"] == ["exchanges"]
    item = schema["properties"]["exchanges"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {
        "source_index",
        "target_index",
        "label",
        "flow",
        "sync",
        "response_label",
    }
    assert item["properties"]["response_label"]["anyOf"] == [
        {
            "type": "string",
            "minLength": 1,
            "maxLength": contract.CONNECTION_LABEL_MAX_CHARS,
        },
        {"type": "null"},
    ]


@pytest.mark.parametrize("sync", [500, 501])
@pytest.mark.parametrize(
    "response_label", [None, "Objective, budgets, and guardrails payload"]
)
def test_create_exchange_expands_explicit_reply_independently_of_timing(
    sync, response_label
):
    exchange = {
        "source_index": 1,
        "target_index": 0,
        "label": "Load current objective and constraint scope for optimization cycle",
        "flow": 400,
        "sync": sync,
        "response_label": response_label,
    }
    original = dict(exchange)
    wire, connection_exchanges = generation._parse_connection_response(
        json.dumps({"exchanges": [exchange]}),
        accepted_components=_accepted_components(),
        edge_limit=2,
    )
    forward = {key: value for key, value in exchange.items() if key != "response_label"}
    expected = [forward]
    if response_label is not None:
        expected.append(
            {**forward, "source_index": 0, "target_index": 1, "label": response_label}
        )
    assert wire == {"edges": expected}
    assert connection_exchanges == [
        {
            "request_record_index": 0,
            "response_record_index": 1 if response_label is not None else None,
        }
    ]
    assert exchange == original


def test_create_exchange_mixed_expansion_preserves_order_and_counts_edges():
    paired = _connection_exchanges()["exchanges"][0]
    one_way = {**paired, "label": "enqueue audit", "sync": 501, "response_label": None}
    text = json.dumps({"exchanges": [paired, one_way]})
    wire, connection_exchanges = generation._parse_connection_response(
        text, accepted_components=_accepted_components(), edge_limit=3
    )
    assert [edge["label"] for edge in wire["edges"]] == [
        "requests",
        "response",
        "enqueue audit",
    ]
    assert connection_exchanges == [
        {"request_record_index": 0, "response_record_index": 1},
        {"request_record_index": 2, "response_record_index": None},
    ]
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        generation._parse_connection_response(
            text, accepted_components=_accepted_components(), edge_limit=2
        )


@pytest.mark.asyncio
async def test_connection_create_returns_pairing_for_each_expanded_exchange(
    monkeypatch,
):
    first = _connection_exchanges()["exchanges"][0]
    one_way = {
        **first,
        "label": "send audit notice",
        "sync": 501,
        "response_label": None,
    }
    second = {
        **first,
        "source_index": 1,
        "target_index": 0,
        "label": "read status",
        "response_label": "status result",
    }

    async def fake_stream(**_kwargs):
        return _response({"exchanges": [first, one_way, second]})

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
    )

    assert [edge["label"] for edge in result["wire"]["edges"]] == [
        "requests",
        "response",
        "send audit notice",
        "read status",
        "status result",
    ]
    assert result["connection_exchanges"] == [
        {"request_record_index": 0, "response_record_index": 1},
        {"request_record_index": 2, "response_record_index": None},
        {"request_record_index": 3, "response_record_index": 4},
    ]
    for exchange in result["connection_exchanges"]:
        request_edge = result["wire"]["edges"][exchange["request_record_index"]]
        response_index = exchange["response_record_index"]
        if response_index is not None:
            response_edge = result["wire"]["edges"][response_index]
            assert (response_edge["source_index"], response_edge["target_index"]) == (
                request_edge["target_index"],
                request_edge["source_index"],
            )


@pytest.mark.parametrize(
    "change",
    [
        {"response_label": ""},
        {"response_label": "  "},
        {"response_label": False},
        {"response_label": 42},
        {"response_label": []},
        {"response_label": "x" * (contract.CONNECTION_LABEL_MAX_CHARS + 1)},
        {"sync": True},
        {"sync": 500.0},
        {"sync": "500"},
        {"sync": 999},
        {"source_index": False},
        {"target_index": 9},
        {"flow": True},
        {"flow": 999},
    ],
)
def test_create_exchange_rejects_invalid_fields(change):
    exchange = {**_connection_exchanges()["exchanges"][0], **change}
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_connection_response(
            json.dumps({"exchanges": [exchange]}),
            accepted_components=_accepted_components(),
            edge_limit=2,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"edges": []},
        {"exchanges": [], "edges": []},
        {"exchanges": None},
        {"exchanges": [None]},
        {"exchanges": [{}]},
        {"exchanges": [{**_connection_exchanges()["exchanges"][0], "id": "invented"}]},
        {"exchanges": [_connection_wire()["edges"][0]]},
    ],
)
def test_create_exchange_rejects_old_format_and_inexact_keys(payload):
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_connection_response(
            json.dumps(payload),
            accepted_components=_accepted_components(),
            edge_limit=2,
        )


def test_create_exchange_rejects_duplicate_return_contract_after_expansion():
    paired = _connection_exchanges()["exchanges"][0]
    duplicate = {
        **paired,
        "source_index": 1,
        "target_index": 0,
        "label": " RESPONSE ",
        "response_label": None,
    }
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        generation._parse_connection_response(
            json.dumps({"exchanges": [paired, duplicate]}),
            accepted_components=_accepted_components(),
            edge_limit=3,
        )


def test_create_exchange_empty_graph_uses_canonical_connectivity_policy():
    assert generation._parse_connection_response(
        '{"exchanges": []}',
        accepted_components=_accepted_components(),
        edge_limit=0,
    ) == ({"edges": []}, [])


@pytest.mark.asyncio
async def test_structural_connection_retry_uses_exchanges_and_returns_canonical_edges(
    monkeypatch,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_connection_exchanges())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    result = await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="c" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        rejected_candidate=_connection_wire(),
        structural_findings=[
            {"code": "connection_wire_invalid", "path": "edges", "rule": "shape"}
        ],
    )
    assert len(calls) == 1
    assert set(calls[0]["response_schema"]["properties"]) == {"exchanges"}
    assert (
        calls[0]["telemetry"]["metadata"]["schema_version"]
        == "staged_connections_exchanges_v1"
    )
    assert result["wire"] == {
        "edges": [
            _connection_wire()["edges"][0],
            {
                **_connection_wire()["edges"][0],
                "source_index": 1,
                "target_index": 0,
                "label": "response",
            },
        ]
    }
    assert result["connection_exchanges"] == [
        {"request_record_index": 0, "response_record_index": 1}
    ]
