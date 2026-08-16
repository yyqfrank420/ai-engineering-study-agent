import hashlib
import json

import pytest

from agent.nodes import staged_graph_generation as generation
from agent.stream_utils import StructuredLLMResponse


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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


def _response(payload: dict) -> StructuredLLMResponse:
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
            accepted_components=[
                {"index": 0, "id": "n1", "label": "Request gateway"},
                {"index": 1, "id": "n2", "label": "Request service"},
            ],
            state=state,
        )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["resolved_maturity"] == "prototype"
    assert "Use prototype criteria only." in prompt
    assert "Do not add production-only controls" in prompt


@pytest.mark.asyncio
async def test_correction_prompt_preserves_bounded_reason_and_record_indexes(
    monkeypatch,
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
                "reason": "x" * 900,
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
            "reason": "x" * generation._MAX_RESPONSIBILITY_CHARS,
            "record_indexes": [0, 2],
        }
    ]


@pytest.mark.asyncio
async def test_component_generation_uses_kimi_high_one_attempt_and_safe_telemetry(
    monkeypatch,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="production",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        state={"user_id": "user-1", "session_id": "thread-1", "is_production": True},
    )

    assert result["wire"] == _component_wire()
    assert len(result["prompt_fingerprint"]) == 64
    assert calls[0]["model"] == "kimi-k3"
    assert calls[0]["effort"] == "high"
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_components_v1"
    assert "request" not in calls[0]["telemetry"]["metadata"]


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
                {"index": 0, "id": "server-a"},
                {"index": 1, "id": "server-b"},
            ],
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
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="prototype",
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
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "edge_missing" in prompt
    assert "<instructions>" not in prompt
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
            write_set=write_set,
            upstream_fingerprint="e" * 64,
            attempt=1,
            prior_prompt_fingerprint="f" * 64,
            prior_write_set_fingerprint="f" * 64,
            structural_findings=[{"code": "failed", "path": "wire", "rule": "shape"}],
        )
