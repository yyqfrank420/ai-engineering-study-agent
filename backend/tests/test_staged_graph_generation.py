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
    if connection_key == "initial_connections":
        assert len(wire["edges"]) == 28
        with pytest.raises(
            generation.StagedGenerationError, match="connection_wire_unreachable"
        ):
            generation._parse_connection_wire(
                json.dumps(wire), accepted_components=accepted_components, edge_limit=30
            )
        with pytest.raises(contract.GraphContractError, match="must be reachable"):
            contract.project_graph_data(build)
        return

    assert (
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=accepted_components, edge_limit=30
        )
        == wire
    )
    graph = contract.project_graph_data(build)
    assert len(graph["nodes"]) == 11
    assert len(graph["edges"]) == 25
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
            _component_wire() if stage == "components" else _connection_wire()
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
    else:
        assert prompt_input["architecture_context"] is None
        assert "both directions of a synchronous request-response" in prompt
        assert "needs a distinct reverse response edge" in prompt
        assert (
            "Route each supporting branch to a rejoin or observable outcome" in prompt
        )


@pytest.mark.asyncio
async def test_connection_prompt_carries_authoritative_accepted_context(monkeypatch):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_connection_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
    )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_connections_v7"
    )
    assert prompt_input["accepted_context"] == _accepted_context()
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
        "Observation-only monitoring may terminate at a durable telemetry/log sink"
        in prompt
    )


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
async def test_component_generation_uses_configured_model_high_one_attempt_and_safe_telemetry(
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
    assert calls[0]["effort"] == "high"
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["timeout_seconds"] == timeout_seconds
    assert calls[0]["telemetry"]["metadata"]["allocated_timeout_s"] == timeout_seconds
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_components_v11"
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
                "edges": [
                    {
                        "source_index": 0,
                        "target_index": 9,
                        "label": "bad",
                        "flow": 400,
                        "sync": 500,
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
        return _response({"edges": edges})

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
        return _response({"edges": []})

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


@pytest.mark.parametrize(
    "change",
    [
        {"updates": {"slot_1": {"label": "unauthorized"}}},
        {"updates": {"slot_0": {"label": "dispatch", "flow": 401}}},
        {"updates": {}},
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
        ([True, True], [(0, 1, 402), (1, 0, 400)], False),
        ([True, False, True], [(0, 1, 400), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 401), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 402), (1, 2, 400)], False),
        ([True, False, True], [(0, 1, 400), (1, 2, 403)], False),
        ([True, False, True], [(1, 0, 400), (1, 2, 400)], False),
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
    ],
)
def test_pull_root_requires_outward_primary_runtime_contract(
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
def test_component_executable_ownership_is_shared_and_production_only(maturity):
    from agent.architecture_rubric import RUBRIC_CRITERIA, staged_review_requirements
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
    generated = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]
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
    base_depth = RUBRIC_CRITERIA["selected_depth"][1]
    selected_depth = generated["selected_depth"]
    if maturity == "prototype":
        assert selected_depth == base_depth
    else:
        assert selected_depth.startswith(base_depth)
        assert (
            "Before freezing the component set, require named executable ownership"
            in selected_depth
        )
        assert (
            "applicable to declared responsibilities and capabilities" in selected_depth
        )
        assert (
            "external_effects requires controlled execution, reconciliation, and compensation"
            in selected_depth
        )
        assert (
            "retrieval_or_reuse requires validation, reuse lifecycle management, and invalidation"
            in selected_depth
        )
        assert (
            "learning_or_release requires curated evidence, offline evaluation, reviewed release, canary, promotion, and rollback"
            in selected_depth
        )
        assert "Existing components may own compatible operations" in selected_depth
        assert (
            "do not require a separate component for every checklist step"
            in selected_depth
        )
        assert (
            "A datastore, registry, or audit label, or an assumption alone, cannot execute evaluation, release, or control"
            in selected_depth
        )


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
