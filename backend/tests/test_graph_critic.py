import json
from copy import deepcopy

import pytest
from config import settings

from adapters.llm_adapter import _anthropic_response_schema
from agent.nodes.graph_critic import (
    CriticProtocolError,
    _GRAPH_CRITIC_PROMPT_VERSION,
    _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA,
    _GRAPH_CRITIC_RESPONSE_SCHEMA,
    _GRAPH_CRITIC_SYSTEM,
    _MODEL_LAYER_FIELDS,
    _RUBRIC_CODE_OWNERS,
    _RUBRIC_CODES,
    _TOPOLOGY_PROOF_GUARANTEES,
    _canonicalise_review_protocol,
    _critic_system,
    _deterministic_render_review,
    _deterministic_review,
    _lock_unchanged_passed_layers,
    _needs_repair_completion,
    _preflight_review_protocol,
    _merge_monotonic_repair_completion,
    _review_packet,
    _validate_repair_contract,
    _validate_review_protocol,
    graph_critic_node,
)
from agent.graph import _route_after_review
from agent.graph_repair_contract import REPAIR_LAYER_PATCH_FIELDS
from agent.nodes.graph_worker import _GRAPH_PATCH_KEYS
from agent.stream_utils import StructuredLLMResponse


def _structured_response(
    payload,
    *,
    finish_reason="end_turn",
):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return StructuredLLMResponse(
        text=text,
        finish_reason=finish_reason,
        input_tokens=1,
        output_tokens=1,
        provider="anthropic",
        model=settings.graph_qa_model,
    )


def _layer(status="pass", score=0.9, *, findings=None, **selectors):
    return {
        "status": status,
        "score": score,
        "blocking_findings": list(findings or []),
        "deterministic_finding_ids": list(
            selectors.get("deterministic_finding_ids") or []
        ),
        "node_ids": list(selectors.get("node_ids") or []),
        "edge_selectors": list(selectors.get("edge_selectors") or []),
        "group_ids": list(selectors.get("group_ids") or []),
        "composition_fields": list(selectors.get("composition_fields") or []),
        "sequence_indexes": list(selectors.get("sequence_indexes") or []),
        "assumption_indexes": list(selectors.get("assumption_indexes") or []),
        "context_node_ids": list(selectors.get("context_node_ids") or []),
        "addition_count": int(selectors.get("addition_count", 0)),
        "composition_append_counts": dict(
            selectors.get("composition_append_counts") or {}
        ),
        "reason": "The artifact layer was assessed against the request.",
    }


def _repair_contract(
    *,
    scope="none",
    failed_layer=None,
    findings=None,
    score=0.9,
    layer_selectors=None,
):
    layers = {
        layer: _layer(score=score)
        for layer in (
            "components",
            "connections",
            "composition",
            "render",
        )
    }
    if failed_layer is not None:
        selectors = (layer_selectors or {}).get(failed_layer, {})
        layers[failed_layer] = _layer(
            "fail",
            min(score, 0.7),
            findings=findings or ["Repair this layer."],
            **selectors,
        )
    return {"repair_scope": scope, "layers": layers}


def _model_layer(layer):
    assessment = {
        "status": "pass",
        "score": 0.9,
        "finding_codes": [],
        "deterministic_finding_indexes": [],
        "context_indexes": [],
        "context_node_indexes": [],
    }
    if layer == "components":
        assessment["node_indexes"] = []
        assessment["addition_count"] = 0
    elif layer == "connections":
        assessment["edge_indexes"] = []
        assessment["addition_count"] = 0
    elif layer == "composition":
        assessment.update(
            {
                "group_indexes": [],
                "composition_fields": [],
                "sequence_indexes": [],
                "assumption_indexes": [],
                "group_addition_count": 0,
                "sequence_addition_count": 0,
                "assumption_addition_count": 0,
            }
        )
    return [assessment[field] for field in _MODEL_LAYER_FIELDS[layer]]


def _set_model_layer(payload, layer, **values):
    fields = _MODEL_LAYER_FIELDS[layer]
    row = payload["layers"][layer]
    for field, value in values.items():
        row[fields.index(field)] = value


def _passing_review_payload(*, strengths=None, advice=None, topology_proofs=None):
    _ = strengths, advice
    return {
        "repair_scope": "none",
        "layers": {
            layer: _model_layer(layer)
            for layer in (
                "components",
                "connections",
                "composition",
                "render",
            )
        },
        "topology_proofs": (
            topology_proofs
            if topology_proofs is not None
            else {
                guarantee: ["not_applicable", [], []]
                for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
            }
        ),
    }


async def _accept_diagram(graph):
    return {
        "screenshot_base64": "private-render",
        "report": {
            "rendered_nodes": len(graph["nodes"]),
            "rendered_edges": len(graph["edges"]),
            "overlap_count": 0,
            "clipped_nodes": 0,
            "clipped_edges": 0,
            "minimum_text_px": 12,
        },
    }


async def _ignore_event(_event):
    return None


def _critic_state(*, graph=None, complexity="prototype"):
    return {
        "graph_data": graph or _domain_graph(),
        "graph_changed": True,
        "user_message": "growth marketing multi-agent system",
        "complexity": complexity,
        "send": _ignore_event,
        "await_diagram_evaluation": _accept_diagram,
        "user_id": "user-1",
        "session_id": "thread-1",
    }


def test_semantic_critic_rejects_cache_replay_or_retry_gate_bypasses():
    assert _GRAPH_CRITIC_PROMPT_VERSION == "architecture_critic_v41"
    assert "gate-preserving reuse" in _GRAPH_CRITIC_SYSTEM
    assert "reuse stores accepted" in _GRAPH_CRITIC_SYSTEM
    assert "post-gate artifacts" in _GRAPH_CRITIC_SYSTEM
    assert "rejoins the gate" in _GRAPH_CRITIC_SYSTEM
    assert "inspect directed paths, not vocabulary" in _GRAPH_CRITIC_SYSTEM
    assert "Carrying a retry key is not durable" in _GRAPH_CRITIC_SYSTEM
    assert (
        "Rejection stops before execution and is not compensation"
        in _GRAPH_CRITIC_SYSTEM
    )
    assert "Sanitization does" in _GRAPH_CRITIC_SYSTEM
    assert "not make retrieved text trusted" in _GRAPH_CRITIC_SYSTEM
    assert "items 17-27 are blocking" in _GRAPH_CRITIC_SYSTEM
    assert "A passing proof cites the complete actual" in _critic_system(
        require_topology_proofs=True
    )
    assert "Do not stop after finding the first defect" in _GRAPH_CRITIC_SYSTEM
    assert "event-stream systems define bounded" in _GRAPH_CRITIC_SYSTEM
    assert "backpressure and overload behavior" in _GRAPH_CRITIC_SYSTEM
    assert "partition/order or event-time semantics" in _GRAPH_CRITIC_SYSTEM
    assert "replay/checkpoint" in _GRAPH_CRITIC_SYSTEM
    assert "compatible schema evolution" in _GRAPH_CRITIC_SYSTEM
    assert "at least two endpoint identities" in _GRAPH_CRITIC_SYSTEM


def test_repair_contract_has_exactly_four_mece_layers_without_duplicate_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {"source": "intake", "target": "gate", "label": "submit"}
                ]
            }
        },
    )

    _validate_repair_contract(contract, graph=graph)

    assert list(contract["layers"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    contract["layers"]["connections"]["edge_selectors"] *= 2
    with pytest.raises(ValueError, match="must not contain duplicates"):
        _validate_repair_contract(contract, graph=graph)


def test_component_additions_require_connection_additions():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"addition_count": 1}},
    )

    with pytest.raises(ValueError, match="connection"):
        _validate_repair_contract(contract, graph=graph)


def test_component_additions_in_a_grouped_graph_require_composition_groups():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [
            {
                "id": "runtime",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["intake", "gate"],
            }
        ],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"addition_count": 1}},
    )
    contract["layers"]["connections"] = _layer(
        "fail",
        0.7,
        findings=["Connect the missing component."],
        addition_count=1,
    )

    with pytest.raises(ValueError, match="groups"):
        _validate_repair_contract(contract, graph=graph)


def test_repair_layer_patch_fields_are_a_mece_partition():
    owners = [
        owner
        for layer_fields in REPAIR_LAYER_PATCH_FIELDS.values()
        for owner in layer_fields
    ]

    assert set(REPAIR_LAYER_PATCH_FIELDS) == set(_MODEL_LAYER_FIELDS)
    assert set(owners) == _GRAPH_PATCH_KEYS
    assert len(owners) == len(set(owners))


def test_all_four_artifact_layers_must_be_scored():
    contract = _repair_contract()
    for assessment in contract["layers"].values():
        assessment["status"] = "not_applicable"
        assessment["score"] = 0.0

    with pytest.raises(ValueError, match="status must be pass or fail"):
        _validate_repair_contract(contract, graph={})

    layer_schema = _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["layers"]
    assert list(layer_schema["properties"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    assert layer_schema["properties"]["components"] == {"$ref": "#/$defs/layer_row"}
    assert (
        set(
            _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["topology_proofs"]["properties"]
        )
        == _TOPOLOGY_PROOF_GUARANTEES
    )


def test_model_indexes_are_expanded_to_exact_locked_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "connections",
        status="fail",
        score=0.7,
        finding_codes=[5],
        edge_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload, graph=graph, deterministic_findings=[], review_context=[]
    )

    assert list(normalized["repair_contract"]["layers"]) == [
        "components",
        "connections",
        "composition",
        "render",
    ]
    assert normalized["repair_contract"]["layers"]["connections"]["edge_selectors"] == [
        {"source": "intake", "target": "gate", "label": "submit"}
    ]
    assert normalized["repair_contract"]["layers"]["connections"][
        "blocking_findings"
    ] == ["Repair edge semantics in the connections layer."]
    _validate_repair_contract(normalized["repair_contract"], graph=graph)


def test_model_status_and_score_are_derived_from_blockers():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
    }
    payload = _passing_review_payload()
    _set_model_layer(
        payload,
        "connections",
        status="pass",
        score=0.95,
        finding_codes=[5],
        edge_indexes=[0],
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    layers = normalized["repair_contract"]["layers"]

    assert layers["connections"]["status"] == "fail"
    assert layers["connections"]["score"] < 0.78
    assert layers["components"]["status"] == "pass"
    assert layers["components"]["score"] == 0.9


def test_scorecard_preflight_rejects_low_score_without_a_blocker():
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(payload, "components", score=0.0)

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )

    assert caught.value.path == "layers.components"
    assert caught.value.rule == "missing_finding"


def test_scorecard_preflight_reports_independent_row_defects_together():
    payload = _passing_review_payload(topology_proofs={})
    _set_model_layer(payload, "components", node_indexes=[4])
    _set_model_layer(payload, "connections", edge_indexes=[7])

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
        )

    assert "layers.components.node_indexes:invalid_reference" in str(caught.value)
    assert "layers.connections.edge_indexes:invalid_reference" in str(caught.value)


def test_scorecard_preflight_reports_independent_proof_defects_together():
    payload = _passing_review_payload()
    guarantees = sorted(_TOPOLOGY_PROOF_GUARANTEES)[:2]
    for guarantee in guarantees:
        payload["topology_proofs"][guarantee] = ["pass", [], []]

    with pytest.raises(CriticProtocolError) as caught:
        _preflight_review_protocol(
            payload,
            graph={"nodes": [], "edges": []},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=True,
        )

    for guarantee in guarantees:
        assert f"topology_proofs.{guarantee}:missing_evidence" in str(caught.value)


@pytest.mark.asyncio
async def test_protocol_correction_receives_all_repair_algebra_defects(monkeypatch):
    invalid = _passing_review_payload(topology_proofs={})
    _set_model_layer(invalid, "components", node_indexes=[0])
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        invalid,
        "connections",
        status="fail",
        score=0.7,
        finding_codes=[connection_code],
        addition_count=1,
    )
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = invalid if len(calls) == 1 else _passing_review_payload(
            topology_proofs={}
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    graph["nodes"][0]["id"] = "selected"
    result = await graph_critic_node(_critic_state(graph=graph))

    assert result["graph_review"]["approved"] is True
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "pass status cannot expose editable selectors" in correction
    assert "connection additions require at least two" in correction


def test_critic_schema_keeps_named_layers_without_repeating_rubric_names():
    layer_schemas = _GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]["layers"]["properties"]
    for layer in ("components", "connections", "composition", "render"):
        assert layer_schemas[layer] == {"$ref": "#/$defs/layer_row"}
    schema_text = json.dumps(_GRAPH_CRITIC_RESPONSE_SCHEMA, separators=(",", ":"))
    assert len(schema_text) < 1_500
    assert "domain_specificity" not in schema_text


def test_anthropic_schema_transform_preserves_critic_definitions_and_refs():
    transformed = _anthropic_response_schema(_GRAPH_CRITIC_RESPONSE_SCHEMA)
    prototype = _anthropic_response_schema(_GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA)

    assert transformed["$defs"] == _GRAPH_CRITIC_RESPONSE_SCHEMA["$defs"]
    assert transformed["properties"]["layers"]["properties"]["components"] == {
        "$ref": "#/$defs/layer_row"
    }
    assert transformed["properties"]["topology_proofs"]["properties"][
        "state_effect_reconciliation"
    ] == {"$ref": "#/$defs/proof_row"}
    assert prototype["$defs"] == {
        "layer_row": _GRAPH_CRITIC_RESPONSE_SCHEMA["$defs"]["layer_row"]
    }
    assert prototype["properties"]["topology_proofs"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }


@pytest.mark.parametrize("layer", list(_MODEL_LAYER_FIELDS))
@pytest.mark.parametrize("length_change", [-1, 1])
def test_model_layer_rows_require_the_exact_layer_arity(layer, length_change):
    payload = _passing_review_payload()
    row = payload["layers"][layer]
    payload["layers"][layer] = row[:-1] if length_change < 0 else [*row, []]

    with pytest.raises(ValueError, match=f"{layer} scorecard row must contain"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize("length", [1, 2, 4])
def test_model_proof_rows_require_exact_status_and_edge_indexes(length):
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["not_applicable"] * length

    with pytest.raises(ValueError, match=f"topology_proofs.{guarantee} is malformed"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


def test_topology_proof_validation_follows_resolved_depth():
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["pass", [], []]

    prototype = _canonicalise_review_protocol(
        payload,
        graph={},
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )

    assert prototype["topology_proofs"] == []
    with pytest.raises(CriticProtocolError, match="pass requires evidence") as error:
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
            require_topology_proofs=True,
        )
    assert error.value.path == f"topology_proofs.{guarantee}"
    assert error.value.rule == "missing_evidence"


def test_protocol_errors_expose_only_safe_coordinates():
    payload = _passing_review_payload()
    _set_model_layer(payload, "components", status="PRIVATE_SENTINEL")

    with pytest.raises(CriticProtocolError) as error:
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )

    assert error.value.path == "layers.components.status"
    assert error.value.rule == "invalid_enum"
    assert "PRIVATE_SENTINEL" not in str(error.value)


@pytest.mark.parametrize(
    ("layer", "field", "value", "match"),
    [
        ("components", "status", True, "status must be pass or fail"),
        ("components", "score", "0.9", "score must be between zero and one"),
        ("components", "finding_codes", 1, "unknown rubric code"),
        ("components", "node_indexes", ["0"], "valid zero-based indexes"),
        ("composition", "composition_fields", [0], "unknown token"),
    ],
)
def test_model_layer_rows_reject_position_type_swaps(layer, field, value, match):
    payload = _passing_review_payload()
    _set_model_layer(payload, layer, **{field: value})

    with pytest.raises(ValueError, match=match):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [], "groups": []},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize(
    "codes",
    [[-1], [0], [28], [1.0], [True], ["domain_specificity"]],
)
def test_model_rubric_codes_reject_values_outside_the_numbered_codebook(codes):
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "components",
        status="fail",
        score=0.7,
        finding_codes=codes,
    )

    with pytest.raises(ValueError, match="unknown rubric code"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": []},
            deterministic_findings=[],
            review_context=[],
        )


def test_model_rubric_codes_reject_duplicates():
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "components",
        status="fail",
        score=0.7,
        finding_codes=[1, 1],
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": []},
            deterministic_findings=[],
            review_context=[],
        )


def test_every_numbered_rubric_code_expands_to_its_canonical_finding():
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    for layer in _MODEL_LAYER_FIELDS:
        owned_codes = [
            index
            for index, code in enumerate(_RUBRIC_CODES, start=1)
            if _RUBRIC_CODE_OWNERS[code] == layer
        ]
        values = {"status": "fail", "score": 0.7, "finding_codes": owned_codes}
        if layer == "composition":
            values["composition_fields"] = ["assumptions"]
        _set_model_layer(payload, layer, **values)

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": []},
        deterministic_findings=[],
        review_context=[],
    )

    for layer in _MODEL_LAYER_FIELDS:
        assert normalized["repair_contract"]["layers"][layer]["blocking_findings"] == [
            f"Repair {code.replace('_', ' ')} in the {layer} layer."
            for code in _RUBRIC_CODES
            if _RUBRIC_CODE_OWNERS[code] == layer
        ]


@pytest.mark.parametrize(
    ("layer", "code", "owner"),
    [
        ("components", 5, "connections"),
        ("connections", 6, "composition"),
        ("composition", 8, "render"),
        ("render", 1, "components"),
    ],
)
def test_rubric_codes_cannot_unlock_a_layer_they_do_not_own(layer, code, owner):
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    values = {"status": "fail", "score": 0.7, "finding_codes": [code]}
    if layer == "composition":
        values["composition_fields"] = ["assumptions"]
    _set_model_layer(payload, layer, **values)

    with pytest.raises(ValueError, match=f"belongs to the {owner} layer, not {layer}"):
        _canonicalise_review_protocol(
            payload,
            graph={},
            deterministic_findings=[],
            review_context=[],
        )


@pytest.mark.parametrize("finding_codes", [[17], [5]])
def test_failed_topology_proof_requires_connections_code_17(finding_codes):
    graph = {
        "nodes": [
            {"id": "source", "label": "Source"},
            {"id": "target", "label": "Target"},
        ],
        "edges": [],
    }
    payload = _passing_review_payload()
    guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    payload["topology_proofs"][guarantee] = ["fail", [], []]
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "connections",
        status="fail",
        score=0.7,
        finding_codes=finding_codes,
        context_node_indexes=[0, 1],
        addition_count=1,
    )

    if finding_codes == [5]:
        with pytest.raises(ValueError, match="topology_enforced_guarantees"):
            _canonicalise_review_protocol(
                payload,
                graph=graph,
                deterministic_findings=[],
                review_context=[],
            )
        return

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
    )
    assert normalized["topology_proofs"][0]["reason"].startswith("Repair the failed ")
    assert (
        normalized["topology_proofs"][0]["reason"]
        in normalized["repair_contract"]["layers"]["connections"]["blocking_findings"]
    )
    _validate_review_protocol(
        normalized,
        require_topology_proofs=True,
        graph=graph,
    )


@pytest.mark.parametrize(
    ("field", "value", "deterministic_findings", "review_context", "match"),
    [
        (
            "finding_codes",
            [1],
            [],
            [],
            "failed components layer must cite a node or declare additions",
        ),
        (
            "deterministic_finding_indexes",
            [0],
            [
                {
                    "id": "deterministic_1",
                    "finding": "Missing required control.",
                    "owner_layer": "components",
                }
            ],
            [],
            "failed components layer must cite a node or declare additions",
        ),
        ("node_indexes", [0], [], [], "cannot expose editable selectors"),
        (
            "context_indexes",
            [0],
            [],
            ["Architect commitment: preserve trust."],
            "cannot cite repair context",
        ),
    ],
)
def test_passing_component_layer_is_locked_at_the_model_boundary(
    field,
    value,
    deterministic_findings,
    review_context,
    match,
):
    payload = _passing_review_payload()
    _set_model_layer(payload, "components", **{field: value})

    if field == "context_indexes":
        with pytest.raises(ValueError, match=match):
            _canonicalise_review_protocol(
                payload,
                graph={"nodes": [{"id": "intake"}]},
                deterministic_findings=deterministic_findings,
                review_context=review_context,
            )
        return

    normalized = _canonicalise_review_protocol(
        payload,
        graph={"nodes": [{"id": "intake"}]},
        deterministic_findings=deterministic_findings,
        review_context=review_context,
    )
    with pytest.raises(ValueError, match=match):
        _validate_review_protocol(
            normalized,
            require_topology_proofs=False,
            graph={"nodes": [{"id": "intake"}]},
            deterministic_findings=deterministic_findings,
        )


def test_missing_record_context_is_actionable_without_unlocking_node_anchors():
    graph = {
        "nodes": [
            {"id": "approval", "label": "Exact action approval"},
            {"id": "executor", "label": "Bounded executor"},
        ],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "connections",
        status="fail",
        score=0.7,
        finding_codes=[4],
        context_indexes=[0],
        context_node_indexes=[0, 1],
        addition_count=1,
    )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=["Architect commitment: bind approval to the exact action."],
    )
    layer = normalized["repair_contract"]["layers"]["connections"]

    assert layer["node_ids"] == []
    assert layer["edge_selectors"] == []
    assert layer["context_node_ids"] == ["approval", "executor"]
    assert layer["addition_count"] == 1
    assert layer["blocking_findings"] == [
        "Repair safe action boundary in the connections layer.",
        "Repair context for the connections layer. Node anchors: approval "
        "(Exact action approval), executor (Bounded executor). Obligations: "
        "Architect commitment: bind approval to the exact action.",
    ]
    _validate_repair_contract(normalized["repair_contract"], graph=graph)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("context_indexes", [1], "valid zero-based indexes"),
        ("context_node_indexes", [2], "valid zero-based indexes"),
    ],
)
def test_repair_context_rejects_out_of_range_indexes(field, value, match):
    graph = {
        "nodes": [{"id": "approval", "label": "Approval"}],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "components",
        status="fail",
        score=0.7,
        finding_codes=[1],
        **{field: value},
    )

    with pytest.raises(ValueError, match=match):
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=[],
            review_context=["Architect commitment: use domain names."],
        )


def test_passing_layer_cannot_expose_repair_context():
    payload = _passing_review_payload()
    _set_model_layer(payload, "components", context_node_indexes=[0])

    with pytest.raises(ValueError, match="passing components layer"):
        _canonicalise_review_protocol(
            payload,
            graph={"nodes": [{"id": "intake", "label": "Intake"}]},
            deterministic_findings=[],
            review_context=[],
        )


def test_model_index_arrays_reject_duplicates_before_locking():
    graph = {
        "nodes": [{"id": "intake"}],
        "edges": [],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "components",
        status="fail",
        score=0.7,
        finding_codes=[1],
        node_indexes=[0, 0],
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _canonicalise_review_protocol(
            payload, graph=graph, deterministic_findings=[], review_context=[]
        )


def test_model_scorecard_rejects_a_missing_mandatory_layer():
    payload = _passing_review_payload()
    payload["layers"].pop("render")

    with pytest.raises(ValueError, match="every artifact layer exactly once"):
        _canonicalise_review_protocol(
            payload, graph={}, deterministic_findings=[], review_context=[]
        )


def test_feedback_edge_finding_cannot_fail_components_while_connections_passes():
    graph = {
        "nodes": [
            {"id": "decision", "label": "Campaign Decision"},
            {"id": "outcome", "label": "Measured Outcome"},
        ],
        "edges": [
            {
                "source": "decision",
                "target": "outcome",
                "label": "records campaign outcome",
                "flow": "runtime",
            }
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    deterministic_review = _deterministic_review(
        "Design a closed-loop campaign optimiser",
        graph,
        "prototype",
    )
    deterministic_findings = [
        {"id": "deterministic_1", **deterministic_review["deterministic_findings"][0]}
    ]
    assert deterministic_findings[0]["owner_layer"] == "connections"

    payload = _passing_review_payload()
    payload["repair_scope"] = "local"
    _set_model_layer(
        payload,
        "components",
        status="fail",
        score=0.7,
        deterministic_finding_indexes=[0],
    )

    with pytest.raises(
        ValueError, match="belongs to the connections layer, not components"
    ):
        _canonicalise_review_protocol(
            payload,
            graph=graph,
            deterministic_findings=deterministic_findings,
            review_context=[],
        )


def test_repair_contract_validation_enforces_deterministic_finding_owner():
    finding_id = "deterministic_1"
    contract = _repair_contract(
        scope="local",
        failed_layer="components",
        findings=["Add the required feedback edge."],
        layer_selectors={
            "components": {"deterministic_finding_ids": [finding_id]},
        },
    )

    with pytest.raises(
        ValueError, match="belongs to the connections layer, not components"
    ):
        _validate_repair_contract(
            contract,
            graph={},
            deterministic_finding_owners={finding_id: "connections"},
        )


def test_repair_contract_rejects_unknown_exact_selectors():
    graph = {
        "nodes": [{"id": "intake"}, {"id": "gate"}],
        "edges": [{"source": "intake", "target": "gate", "label": "submit"}],
        "groups": [{"id": "runtime"}],
    }
    contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {"source": "intake", "target": "gate", "label": "invented"}
                ]
            }
        },
    )

    with pytest.raises(ValueError, match="edge absent from the graph"):
        _validate_repair_contract(contract, graph=graph)


def test_failed_layer_score_must_stay_below_publishable_threshold():
    contract = _repair_contract(scope="local", failed_layer="components")
    contract["layers"]["components"]["score"] = 0.9

    with pytest.raises(ValueError, match="fail score must be below 0.78"):
        _validate_repair_contract(contract, graph={})


def test_graph_caused_render_failure_can_use_one_local_repair():
    contract = _repair_contract(scope="local", failed_layer="composition")
    contract["layers"]["composition"]["composition_fields"] = ["groups"]
    contract["layers"]["render"] = _layer(
        "fail",
        0.7,
        findings=["The screenshot has no clear reading order."],
    )

    _validate_repair_contract(contract, graph={"groups": []})


def test_render_only_failure_cannot_enter_local_patch_lane():
    contract = _repair_contract(scope="local", failed_layer="render")

    with pytest.raises(ValueError, match="must be global for the failed layer ownership"):
        _validate_repair_contract(contract, graph={})


def test_protocol_tokens_are_normalized_without_touching_record_identity():
    payload = _passing_review_payload()
    payload["repair_scope"] = " LOCAL "
    _set_model_layer(payload, "components", status=" PASS ")
    _set_model_layer(
        payload,
        "composition",
        status=" FAIL ",
        score=0.7,
        finding_codes=[12],
        composition_fields=["groups"],
    )

    normalized = _canonicalise_review_protocol(
        payload, graph={}, deterministic_findings=[], review_context=[]
    )

    assert normalized["repair_contract"]["repair_scope"] == "local"
    assert normalized["repair_contract"]["layers"]["components"]["status"] == "pass"
    assert normalized["repair_contract"]["layers"]["composition"][
        "composition_fields"
    ] == ["groups"]


@pytest.mark.parametrize(
    ("model_scope", "failed_layer", "expected_scope", "expected_route"),
    [
        ("global", "connections", "local", "revise"),
        ("local", "render", "global", "reject"),
        ("global", None, "none", "accept"),
    ],
)
def test_repair_scope_is_derived_from_failed_layer_ownership(
    model_scope,
    failed_layer,
    expected_scope,
    expected_route,
):
    graph = _domain_graph()
    payload = _passing_review_payload()
    payload["repair_scope"] = model_scope
    if failed_layer is not None:
        finding_code = next(
            index
            for index, code in enumerate(_RUBRIC_CODES, start=1)
            if _RUBRIC_CODE_OWNERS[code] == failed_layer
        )
        values = {
            "status": "fail",
            "score": 0.7,
            "finding_codes": [finding_code],
        }
        if failed_layer == "connections":
            values["edge_indexes"] = [0]
        _set_model_layer(
            payload,
            failed_layer,
            **values,
        )

    normalized = _canonicalise_review_protocol(
        payload,
        graph=graph,
        deterministic_findings=[],
        review_context=[],
        require_topology_proofs=False,
    )
    _validate_review_protocol(
        normalized,
        require_topology_proofs=False,
        graph=graph,
        deterministic_findings=[],
    )

    assert normalized["repair_contract"]["repair_scope"] == expected_scope
    assert (
        _route_after_review(
            {
                "graph_changed": True,
                "graph_data": {**graph, "design_origin": "applied"},
                "graph_revision_count": 0,
                "graph_review": {
                    "approved": expected_scope == "none",
                    **normalized,
                },
            }
        )
        == expected_route
    )


def test_failed_topology_proof_cannot_hide_behind_passing_layers():
    proofs = _valid_protocol_topology_proofs()
    proofs[0] = {
        **proofs[0],
        "status": "fail",
        "edge_evidence": [],
        "reason": "The reconciliation path is incomplete.",
    }

    _validate_review_protocol(
        _protocol_review(proofs),
        require_topology_proofs=False,
    )
    with pytest.raises(ValueError, match="failed connections layer"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
        )


@pytest.mark.parametrize(
    ("scope", "approved", "expected"),
    [
        ("none", True, "accept"),
        ("local", False, "revise"),
        ("global", False, "reject"),
    ],
)
def test_repair_scope_controls_review_routing(scope, approved, expected):
    failed_layer = (
        None if scope == "none" else ("render" if scope == "global" else "components")
    )
    state = {
        "graph_changed": True,
        "graph_data": {"design_origin": "applied"},
        "graph_revision_count": 0,
        "graph_review": {
            "approved": approved,
            "repair_contract": _repair_contract(
                scope=scope,
                failed_layer=failed_layer,
            ),
        },
    }

    assert _route_after_review(state) == expected


def test_repair_completion_is_merged_with_prior_authority():
    first_edge = {"source": "a", "target": "b", "label": "first"}
    second_edge = {"source": "b", "target": "c", "label": "second"}
    prior = {
        "repair_contract": _repair_contract(
            scope="local",
            failed_layer="connections",
            findings=["Repair the first route."],
            layer_selectors={
                "connections": {
                    "edge_selectors": [first_edge],
                    "context_node_ids": ["a", "b"],
                    "addition_count": 1,
                }
            },
        ),
        "topology_proofs": [],
    }
    completion = {
        "repair_contract": _repair_contract(
            scope="local",
            failed_layer="connections",
            findings=["Repair the second route."],
            layer_selectors={
                "connections": {
                    "edge_selectors": [second_edge],
                    "context_node_ids": ["b", "c"],
                    "addition_count": 2,
                }
            },
        ),
        "topology_proofs": [],
    }

    merged = _merge_monotonic_repair_completion(prior, completion)
    merged_connections = merged["repair_contract"]["layers"]["connections"]
    assert merged_connections["blocking_findings"] == [
        "Repair the first route.",
        "Repair the second route.",
    ]
    assert merged_connections["edge_selectors"] == [first_edge, second_edge]
    assert merged_connections["context_node_ids"] == ["a", "b", "c"]
    assert merged_connections["addition_count"] == 2

    clean_completion = {
        "repair_contract": _repair_contract(),
        "strengths": [],
        "advice": [],
        "topology_proofs": [],
    }
    retained = _merge_monotonic_repair_completion(prior, clean_completion)
    retained_connections = retained["repair_contract"]["layers"]["connections"]
    assert retained_connections["status"] == "fail"
    assert retained_connections["blocking_findings"] == ["Repair the first route."]
    assert retained_connections["edge_selectors"] == [first_edge]


@pytest.mark.parametrize(
    ("scope", "revision_count", "expected"),
    [
        ("local", 0, True),
        ("none", 0, False),
        ("global", 0, False),
        ("local", 1, False),
    ],
)
def test_repair_completion_runs_only_for_initial_local_rejections(
    scope,
    revision_count,
    expected,
):
    review = {
        "review_status": "completed",
        "repair_contract": {"repair_scope": scope},
    }

    assert _needs_repair_completion(review, revision_count) is expected


@pytest.mark.asyncio
async def test_initial_local_rejection_gets_one_monotonic_completion_pass(monkeypatch):
    calls = []
    graph = _domain_graph()
    graph["edges"].append(
        {
            "source": "objective",
            "target": "approval",
            "label": "requires approval",
        }
    )
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        payload["repair_scope"] = "local"
        _set_model_layer(
            payload,
            "connections",
            status="fail",
            score=0.7,
            finding_codes=[connection_code],
            edge_indexes=[0] if len(calls) == 1 else [0, 1],
        )
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state(graph=graph))

    assert len(calls) == 2
    assert calls[0]["telemetry"]["operation"] == "graph_critic"
    assert calls[1]["telemetry"]["operation"] == "graph_critic_repair_completion"
    assert "clean completeness pass" in calls[1]["messages"][0]["content"][-1]["text"]
    assert len(
        result["graph_review"]["repair_contract"]["layers"]["connections"][
            "edge_selectors"
        ]
    ) == 2


@pytest.mark.asyncio
async def test_protocol_correction_is_the_clean_completion_pass(monkeypatch):
    calls = []
    invalid = _passing_review_payload()
    _set_model_layer(invalid, "components", status="invalid")
    local = _passing_review_payload()
    local["repair_scope"] = "local"
    connection_code = next(
        index
        for index, code in enumerate(_RUBRIC_CODES, start=1)
        if _RUBRIC_CODE_OWNERS[code] == "connections"
    )
    _set_model_layer(
        local,
        "connections",
        status="fail",
        score=0.7,
        finding_codes=[connection_code],
        edge_indexes=[0],
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid if len(calls) == 1 else local)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state())

    assert result["graph_review"]["repair_contract"]["repair_scope"] == "local"
    assert [call["telemetry"]["operation"] for call in calls] == [
        "graph_critic",
        "graph_critic_protocol_correction",
    ]
    correction = calls[1]["messages"][0]["content"][-1]["text"]
    assert "clean completeness pass" in correction
    assert "add every independent blocking defect" in correction


def test_unchanged_passed_layers_remain_locked_after_a_local_repair():
    baseline = _domain_graph()
    for index, node in enumerate(baseline["nodes"]):
        node["id"] = f"node_{index}"
    edge = baseline["edges"][0]
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                ]
            }
        },
    )
    candidate = deepcopy(baseline)
    candidate["edges"][0]["description"] = "Carries the repaired bounded event."
    current_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": [candidate["nodes"][0]["id"]]}},
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": baseline,
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        candidate,
    )

    assert review["approved"] is True
    assert review["repair_contract"]["repair_scope"] == "none"
    assert review["repair_contract"]["layers"]["components"]["status"] == "pass"
    assert review["repair_contract"]["layers"]["components"]["node_ids"] == []
    assert set(review["locked_layers"]) == {"components"}


def test_layer_lock_rechecks_connections_when_endpoint_meaning_changes():
    baseline = _domain_graph()
    for index, node in enumerate(baseline["nodes"]):
        node["id"] = f"node_{index}"
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": [baseline["nodes"][0]["id"]]}},
    )
    candidate = deepcopy(baseline)
    candidate["nodes"][0]["description"] = "Now owns a different boundary."
    edge = candidate["edges"][0]
    current_contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                ]
            }
        },
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": baseline,
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        candidate,
    )

    assert review["repair_contract"]["layers"]["connections"]["status"] == "fail"
    assert "connections" not in review.get("locked_layers", [])


def test_layer_lock_rechecks_composition_when_component_meaning_changes():
    baseline = _domain_graph()
    baseline["title"] = "Campaign control loop"
    for index, node in enumerate(baseline["nodes"]):
        node["id"] = f"node_{index}"
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": [baseline["nodes"][0]["id"]]}},
    )
    candidate = deepcopy(baseline)
    candidate["nodes"][0]["description"] = "Now owns a different product boundary."
    current_contract = _repair_contract(
        scope="local",
        failed_layer="composition",
        layer_selectors={"composition": {"composition_fields": ["title"]}},
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": baseline,
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        candidate,
    )

    assert review["repair_contract"]["layers"]["composition"]["status"] == "fail"
    assert "composition" not in review.get("locked_layers", [])


def test_layer_lock_rechecks_connections_when_endpoint_technology_changes():
    baseline = _domain_graph()
    for index, node in enumerate(baseline["nodes"]):
        node["id"] = f"node_{index}"
        node["technology"] = "Bounded application service"
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": [baseline["nodes"][0]["id"]]}},
    )
    candidate = deepcopy(baseline)
    candidate["nodes"][0]["technology"] = "Untrusted vector retrieval corpus"
    edge = candidate["edges"][0]
    current_contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                ]
            }
        },
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": baseline,
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        candidate,
    )

    assert review["repair_contract"]["layers"]["connections"]["status"] == "fail"
    assert "connections" not in review.get("locked_layers", [])


def test_layer_lock_never_erases_a_current_deterministic_finding():
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"]):
        node["id"] = f"node_{index}"
    current_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={
            "components": {
                "node_ids": [graph["nodes"][0]["id"]],
                "deterministic_finding_ids": ["deterministic_1"],
            }
        },
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": deepcopy(graph),
            "graph_review": {
                "repair_contract": _repair_contract(),
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        graph,
        deterministic_findings=[
            {
                "id": "deterministic_1",
                "finding": "Repair the component identity.",
                "owner_layer": "components",
            }
        ],
    )

    assert review["approved"] is False
    assert review["repair_contract"]["layers"]["components"][
        "deterministic_finding_ids"
    ] == ["deterministic_1"]


def test_layer_lock_promotes_a_render_only_residual_to_global_scope():
    baseline = _domain_graph()
    for index, node in enumerate(baseline["nodes"]):
        node["id"] = f"node_{index}"
    edge = baseline["edges"][0]
    prior_contract = _repair_contract(
        scope="local",
        failed_layer="connections",
        layer_selectors={
            "connections": {
                "edge_selectors": [
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "label": edge["label"],
                    }
                ]
            }
        },
    )
    candidate = deepcopy(baseline)
    candidate["edges"][0]["description"] = "Carries the repaired event."
    current_contract = _repair_contract(
        scope="local",
        failed_layer="components",
        layer_selectors={"components": {"node_ids": [candidate["nodes"][0]["id"]]}},
    )
    current_contract["layers"]["render"] = _layer(
        "fail",
        0.6,
        findings=["The rendered topology is clipped."],
    )

    review = _lock_unchanged_passed_layers(
        {
            "repair_baseline_graph_data": baseline,
            "graph_review": {
                "repair_contract": prior_contract,
                "topology_proofs": [],
            },
        },
        {"repair_contract": current_contract, "topology_proofs": []},
        candidate,
    )

    assert review["repair_contract"]["repair_scope"] == "global"
    assert review["review_status"] == "completed"
    assert review["terminal"] is True


def test_required_topology_proofs_reject_missing_or_invented_edges():
    graph = {
        "edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
    }
    value = [
        {
            "guarantee": guarantee,
            "status": "not_applicable",
            "edge_evidence": [],
            "route_claims": [],
            "reason": "This flow class is absent.",
        }
        for guarantee in (
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]
    value.append(
        {
            "guarantee": "state_effect_reconciliation",
            "status": "pass",
            "edge_evidence": [
                {"source": "gate", "target": "writer", "label": "release action"}
            ],
            "route_claims": [{"source": "gate", "target": "writer"}],
            "reason": "The action is supposedly reserved before execution.",
        }
    )

    with pytest.raises(ValueError, match="edge absent from the graph"):
        _validate_review_protocol(
            {
                "repair_contract": _repair_contract(),
                "strengths": [],
                "advice": [],
                "topology_proofs": value,
            },
            require_topology_proofs=True,
            graph=graph,
        )


def test_required_topology_proofs_accept_exact_citations_from_semantic_reviewer():
    graph = {
        "edges": [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
    }
    value = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                [{"source": "proposal", "target": "gate", "label": "submit proposal"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "route_claims": (
                [{"source": "proposal", "target": "gate"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "reason": "The cited path is present."
            if guarantee == "authorization_and_compensation"
            else "This flow class is absent.",
        }
        for guarantee in sorted(
            {
                "state_effect_reconciliation",
                "authorization_and_compensation",
                "retrieval_and_reuse_trust",
                "audit_and_provenance",
                "learning_and_release",
            }
        )
    ]

    _validate_review_protocol(
        {
            "repair_contract": _repair_contract(),
            "strengths": [],
            "advice": [],
            "topology_proofs": value,
        },
        require_topology_proofs=True,
        graph=graph,
    )


@pytest.mark.parametrize(
    ("route_claims", "match"),
    [
        ([{"source": "gate", "target": "proposal"}], "is not directed"),
        ([{"source": "proposal", "target": "proposal"}], "is not directed"),
    ],
)
def test_topology_witness_rejects_unproved_direction_or_cycle(route_claims, match):
    graph = {
        "edges": [
            {"source": "proposal", "target": "gate", "label": "submit proposal"},
        ]
    }
    proofs = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                [graph["edges"][0]]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "route_claims": (
                route_claims if guarantee == "authorization_and_compensation" else []
            ),
            "reason": "The witness is reviewed semantically.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]

    with pytest.raises(ValueError, match=match):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
            graph=graph,
        )


def test_topology_witness_rejects_disconnected_padding():
    graph = {
        "edges": [
            {"source": "proposal", "target": "gate", "label": "submit proposal"},
            {"source": "cache", "target": "metrics", "label": "emit metric"},
        ]
    }
    proofs = [
        {
            "guarantee": guarantee,
            "status": "pass"
            if guarantee == "authorization_and_compensation"
            else "not_applicable",
            "edge_evidence": (
                graph["edges"] if guarantee == "authorization_and_compensation" else []
            ),
            "route_claims": (
                [{"source": "proposal", "target": "gate"}]
                if guarantee == "authorization_and_compensation"
                else []
            ),
            "reason": "The witness is reviewed semantically.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]

    with pytest.raises(ValueError, match="outside every claimed route"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
            graph=graph,
        )


@pytest.mark.parametrize(
    ("guarantee", "label"),
    [
        ("state_effect_reconciliation", "Action Executor"),
        ("authorization_and_compensation", "Supervisor Approval"),
        ("retrieval_and_reuse_trust", "Scoped Answer Cache"),
        ("audit_and_provenance", "Lifecycle Audit Ledger"),
        ("learning_and_release", "Canary Release Gate"),
    ],
)
def test_topology_applicability_is_owned_by_semantic_review_not_label_regex(
    guarantee, label
):
    graph = {
        "nodes": [{"id": "visible", "label": label}],
        "edges": [
            {"source": "visible", "target": "outcome", "label": "returns result"}
        ],
    }
    value = [
        {
            "guarantee": item,
            "status": "not_applicable",
            "edge_evidence": [],
            "route_claims": [],
            "reason": "This flow class is absent.",
        }
        for item in (
            "state_effect_reconciliation",
            "authorization_and_compensation",
            "retrieval_and_reuse_trust",
            "audit_and_provenance",
            "learning_and_release",
        )
    ]

    _validate_review_protocol(
        {
            "repair_contract": _repair_contract(),
            "strengths": [],
            "advice": [],
            "topology_proofs": value,
        },
        require_topology_proofs=True,
        graph=graph,
    )


def test_production_gate_accepts_cache_write_owned_by_acceptance_gate():
    graph = {
        "nodes": [
            {"id": "generator", "label": "Answer Generator"},
            {"id": "validator", "label": "Grounding Validator"},
            {"id": "fallback", "label": "No-Evidence Fallback"},
            {"id": "delivery", "label": "Response Delivery"},
            {"id": "cache", "label": "Answer Cache"},
        ],
        "edges": [
            {"source": "generator", "target": "validator", "label": "submit candidate"},
            {
                "source": "validator",
                "target": "cache",
                "label": "write accepted answer",
            },
            {
                "source": "validator",
                "target": "fallback",
                "label": "reject ungrounded answer",
            },
            {"source": "fallback", "target": "delivery", "label": "deliver abstention"},
            {"source": "cache", "target": "delivery", "label": "serve scoped answer"},
            {
                "source": "delivery",
                "target": "generator",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a production RAG workflow", graph, "production"
    )

    assert review["approved"] is True
    assert not any("cache writes" in item for item in review["missing"])


def test_production_gate_does_not_treat_approval_audit_store_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Permit Request", "type": "client"},
            # Even if the model classifies an audit projection as a control,
            # its ownership noun must keep it from becoming an approval gate.
            {"id": "ledger", "label": "Approval Audit Ledger", "type": "control"},
            {"id": "outcome", "label": "Permit Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "ledger", "label": "records reviewed permit"},
            {
                "source": "ledger",
                "target": "outcome",
                "label": "publishes audit projection",
            },
            {
                "source": "outcome",
                "target": "entry",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design an audited permit workflow", graph, "production"
    )

    assert not any("rejection/cancellation" in item for item in review["missing"])


def test_production_gate_does_not_treat_approved_registry_as_a_decision():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Definition Proposal", "type": "service"},
            {
                "id": "registry",
                "label": "Event Definition Registry",
                "type": "control",
                "description": "Stores approved versioned definitions for canary release.",
            },
            {"id": "outcome", "label": "Definition Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "entry",
                "target": "registry",
                "label": "register approved version",
            },
            {
                "source": "registry",
                "target": "outcome",
                "label": "publish immutable version",
            },
            {
                "source": "outcome",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design controlled event-definition releases",
        graph,
        "production",
    )

    assert not any("approval decision registry" in item for item in review["missing"])


def test_approval_owner_accepts_separate_approval_and_rejection_routes():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Audited Rejection", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {"source": "owner", "target": "lifecycle", "label": "approve exact action"},
            {"source": "owner", "target": "terminal", "label": "reject exact action"},
            {
                "source": "lifecycle",
                "target": "entry",
                "label": "return measured outcome",
                "flow": "feedback",
            },
            {
                "source": "terminal",
                "target": "entry",
                "label": "return rejection outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled external action", graph, "production"
    )

    assert review["approved"] is True


def test_approval_owner_may_persist_both_outcomes_in_complete_durable_envelope():
    graph = {
        "nodes": [
            {"id": "entry", "label": "Action Proposal", "type": "service"},
            {"id": "owner", "label": "Clinical Sign-off", "type": "control"},
            {"id": "lifecycle", "label": "Action Lifecycle", "type": "datastore"},
            {"id": "terminal", "label": "Decision Outcome", "type": "service"},
        ],
        "edges": [
            {"source": "entry", "target": "owner", "label": "submit exact action"},
            {
                "source": "owner",
                "target": "lifecycle",
                "label": "record approve or reject decision",
                "technology": "Signed payload and target envelope",
                "description": (
                    "Persists policy version, expiry, and idempotency key before any lease."
                ),
            },
            {
                "source": "lifecycle",
                "target": "terminal",
                "label": "publish decision outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled clinical action", graph, "production"
    )

    assert review["approved"] is True
    assert not any("approval decision" in item for item in review["missing"])
    assert not any("approval edge" in item for item in review["missing"])


def test_release_controller_may_own_promotion_and_rollback_for_registry_canary():
    graph = {
        "nodes": [
            {"id": "registry", "label": "Model Registry", "type": "datastore"},
            {"id": "controller", "label": "Rollout Controller", "type": "control"},
            {"id": "runtime", "label": "Decision Runtime", "type": "service"},
            {"id": "outcome", "label": "Canary Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "registry",
                "target": "controller",
                "label": "supplies immutable release",
            },
            {"source": "controller", "target": "runtime", "label": "deploy canary"},
            {
                "source": "controller",
                "target": "runtime",
                "label": "promote full production",
            },
            {
                "source": "controller",
                "target": "registry",
                "label": "rollback to prior release",
            },
            {"source": "runtime", "target": "outcome", "label": "measure canary"},
            {
                "source": "outcome",
                "target": "controller",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a controlled model release", graph, "production"
    )

    assert review["approved"] is True
    assert not any("canary" in item.lower() for item in review["missing"])


def test_reservation_store_description_does_not_make_it_an_executor():
    graph = {
        "nodes": [
            {"id": "policy", "label": "Risk Policy", "type": "decision"},
            {
                "id": "reservation",
                "label": "Operation Reservation",
                "type": "datastore",
                "description": "Owns durable execution lifecycle state and leases.",
            },
            {"id": "executor", "label": "Channel Executor", "type": "gateway"},
            {"id": "outcome", "label": "Campaign Outcome", "type": "service"},
        ],
        "edges": [
            {
                "source": "policy",
                "target": "reservation",
                "label": "forward auto-authorized payload",
                "technology": "Signed target envelope",
                "description": "Binds policy version, expiry, and idempotency key.",
            },
            {
                "source": "reservation",
                "target": "executor",
                "label": "lease reserved operation",
            },
            {
                "source": "executor",
                "target": "outcome",
                "label": "execute campaign change",
            },
            {
                "source": "outcome",
                "target": "policy",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design an automatic campaign workflow", graph, "production"
    )

    assert review["approved"] is True
    assert not any("durable reservation state" in item for item in review["missing"])


def test_read_only_external_adapter_is_not_treated_as_effect_executor():
    graph = {
        "nodes": [
            {"id": "reservation", "label": "Query Lifecycle", "type": "datastore"},
            {"id": "adapter", "label": "Ad Platform Adapter", "type": "gateway"},
            {"id": "target", "label": "Ad Platform", "type": "external"},
            {"id": "reconciler", "label": "Query Reconciler", "type": "service"},
        ],
        "edges": [
            {
                "source": "reservation",
                "target": "adapter",
                "label": "lease reserved query",
            },
            {"source": "adapter", "target": "target", "label": "query campaign status"},
            {
                "source": "target",
                "target": "reconciler",
                "label": "return campaign status",
            },
            {
                "source": "reconciler",
                "target": "adapter",
                "label": "NOT_FOUND retry read",
            },
            {
                "source": "reconciler",
                "target": "reservation",
                "label": "return measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(
        "Design a read-only campaign status lookup", graph, "production"
    )

    assert review["approved"] is True
    assert not any("durable reservation" in item for item in review["missing"])


def test_distinct_reconciliation_branch_may_contrast_other_outcomes_and_share_audit():
    graph = {
        "nodes": [
            {"id": "ledger", "label": "Lifecycle Ledger", "type": "datastore"},
            {"id": "adapter", "label": "Fulfilment Adapter", "type": "gateway"},
            {"id": "target", "label": "External Fulfilment", "type": "external"},
            {"id": "reconciler", "label": "Outcome Reconciler", "type": "control"},
            {"id": "audit", "label": "Audit Log", "type": "datastore"},
        ],
        "edges": [
            {
                "source": "ledger",
                "target": "adapter",
                "label": "lease reserved operation",
            },
            {
                "source": "adapter",
                "target": "target",
                "label": "apply fulfilment mutation",
            },
            {"source": "target", "target": "reconciler", "label": "return status"},
            {
                "source": "reconciler",
                "target": "ledger",
                "label": "NOT_FOUND retry reservation",
                "description": "Retries only NOT_FOUND; STILL_UNKNOWN escalates on its own branch.",
            },
            {
                "source": "reconciler",
                "target": "audit",
                "label": "log reconciliation outcomes",
                "description": "Audits COMMITTED, NOT_FOUND, and STILL_UNKNOWN branch results.",
            },
        ],
    }

    review = _deterministic_review(
        "Design a fulfilment integration", graph, "production"
    )

    assert not any(
        "distinct reconciliation branches" in item for item in review["missing"]
    )


def test_domain_specific_connected_topology_passes_local_structural_checks():
    graph = {
        "nodes": [
            {"id": "report", "label": "Missing Bag Report"},
            {"id": "router", "label": "Recovery Route Decision"},
            {"id": "resolution", "label": "Passenger Resolution"},
        ],
        "edges": [
            {
                "source": "report",
                "target": "router",
                "label": "submits verified bag record",
            },
            {
                "source": "router",
                "target": "resolution",
                "label": "returns recovery outcome",
            },
        ],
    }

    review = _deterministic_review(
        "Design an airport baggage recovery workflow",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def _domain_graph():
    return {
        "design_origin": "applied",
        "nodes": [
            {
                "label": "Campaign Objective",
                "description": "Defines ROAS objective and spend constraints",
            },
            {
                "label": "Event Quality Gate",
                "description": "Validates conversion and attribution events",
            },
            {
                "label": "Creative Optimizer",
                "description": "Chooses copy variants for an audience",
            },
            {
                "label": "Approval Policy",
                "description": "Approves risky actions and writes an audit record",
            },
            {
                "label": "Channel Executor",
                "description": "Applies idempotent targeting and bid changes",
            },
            {
                "label": "Outcome Attribution",
                "description": "Observes attributed revenue and campaign outcomes",
            },
        ],
        "edges": [
            {
                "source": "outcome",
                "target": "objective",
                "label": "returns attributed outcomes",
                "description": "Closes the measured optimization loop",
                "type": "loop",
            }
        ],
    }


def test_deterministic_review_accepts_a_domain_control_loop():
    review = _deterministic_review(
        "Design a growth marketing agent that optimizes campaign attribution",
        _domain_graph(),
        "prototype",
    )

    assert review["approved"] is True
    assert review["missing"] == []
    assert review["score"] >= 0.78


@pytest.mark.parametrize(
    ("query", "labels"),
    [
        (
            "Design a municipal water-leak triage system",
            ("Leak Report", "Dispatch Decision", "Repair Outcome"),
        ),
        (
            "Design a telescope transient-alert pipeline",
            ("Sky Event", "Candidate Classifier", "Observer Outcome"),
        ),
        (
            "Design a music-royalty reconciliation service",
            ("Usage Evidence", "Royalty Reconciler", "Dispute Outcome"),
        ),
        (
            "Design an airport baggage recovery workflow",
            ("Missing Bag", "Recovery Router", "Passenger Outcome"),
        ),
    ],
)
def test_feedback_flow_is_a_loop_without_renderer_specific_metadata(query, labels):
    graph = {
        "design_origin": "applied",
        "nodes": [
            {
                "id": "entry",
                "label": labels[0],
                "description": "Captures a verified request.",
            },
            {
                "id": "decision",
                "label": labels[1],
                "description": "Owns the bounded decision.",
            },
            {
                "id": "outcome",
                "label": labels[2],
                "description": "Records the measured outcome.",
            },
        ],
        "edges": [
            {"source": "entry", "target": "decision", "label": "sends verified input"},
            {
                "source": "decision",
                "target": "outcome",
                "label": "records bounded result",
            },
            {
                "source": "outcome",
                "target": "decision",
                "label": "returns measured outcome",
                "flow": "feedback",
            },
        ],
    }

    review = _deterministic_review(query, graph, "prototype")

    assert review["approved"] is True
    assert review["missing"] == []


def test_deterministic_gate_does_not_guess_semantics_from_prose_vocabulary():
    graph = _domain_graph()
    graph["nodes"][-1] = {
        "label": "Outcome Evaluator",
        "description": "Computes campaign performance metrics for the feedback loop",
    }

    review = _deterministic_review(
        "Design a production growth marketing agent for campaign performance",
        graph,
        "production",
    )

    assert review["approved"] is True
    assert review["missing"] == []


def test_generic_book_vocabulary_is_rejected_before_publication():
    graph = {
        "nodes": [
            {"label": label, "description": "Generic book concept"}
            for label in (
                "Agent",
                "Tool Use",
                "Planning",
                "Evaluation",
                "Foundation Model",
                "Generation",
            )
        ],
        "edges": [
            {
                "source": "agent",
                "target": "planning",
                "label": "returns measured outcome",
                "type": "loop",
            }
        ],
    }

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_one_standalone_generic_label_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"][0] = {"label": "Agent", "description": "Owns the campaign objective"}

    review = _deterministic_review(
        "growth and performance marketing AI agent system",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("generic book concepts" in item for item in review["missing"])


def test_disconnected_architecture_is_rejected_before_publication():
    graph = _domain_graph()
    graph["nodes"] = [
        {**node, "id": f"node_{index}"} for index, node in enumerate(graph["nodes"])
    ]

    review = _deterministic_review(
        "Design a growth marketing optimization system",
        graph,
        "production",
    )

    assert review["approved"] is False
    assert any("Connect every component" in item for item in review["missing"])


def test_read_only_design_does_not_invent_an_external_write_boundary():
    graph = {
        "nodes": [
            {
                "id": "request",
                "label": "Research Request",
                "description": "Captures the research question",
            },
            {
                "id": "retriever",
                "label": "Evidence Retriever",
                "description": "Retrieves cited source passages",
            },
            {
                "id": "composer",
                "label": "Answer Composer",
                "description": "Builds a grounded answer",
            },
        ],
        "edges": [
            {
                "source": "request",
                "target": "retriever",
                "label": "submits ACL-scoped query",
            },
            {
                "source": "retriever",
                "target": "composer",
                "label": "returns cited passages",
            },
        ],
    }

    review = _deterministic_review(
        "Design a research assistant system",
        graph,
        "prototype",
    )

    assert review["approved"] is True
    assert not any("approval" in item for item in review["missing"])
    assert not any("feedback" in item for item in review["missing"])


def test_explicit_optimisation_request_requires_a_measured_feedback_edge():
    graph = {
        "nodes": [
            {"id": "input", "label": "Observed Outcome"},
            {"id": "decision", "label": "Allocation Decision"},
            {"id": "result", "label": "Allocation Result"},
        ],
        "edges": [
            {
                "source": "input",
                "target": "decision",
                "label": "supplies measured evidence",
            },
            {
                "source": "decision",
                "target": "result",
                "label": "returns bounded allocation",
            },
        ],
    }

    review = _deterministic_review(
        "Design a system that continuously optimizes allocations from measured outcomes",
        graph,
        "prototype",
    )

    assert review["approved"] is False
    assert any("feedback edge" in item for item in review["missing"])


def test_render_gate_rejects_overlap_clipping_or_missing_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 0,
                "overlap_count": 1,
                "clipped_nodes": 1,
                "clipped_edges": 1,
                "minimum_text_px": 12,
            },
        },
    )

    assert review["approved"] is False
    assert review["terminal"] is True
    assert review["failure_code"] == "diagram_evaluation_layout_rejected"
    assert any("actual candidate" in item for item in review["missing"])
    assert any("overlapping" in item for item in review["missing"])


def test_render_gate_accepts_a_complete_readable_browser_capture():
    graph = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "valid-bounded-image",
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 0,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
            },
        },
    )

    assert review["approved"] is True
    assert review["terminal"] is False


def test_render_gate_rejects_missing_overview_and_group_labels_or_overlapping_zones():
    graph = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"source": "a", "target": "b"}],
    }
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "valid-bounded-image",
            "report": {
                "rendered_nodes": 2,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
                "overview_required_edge_labels": 1,
                "visible_overview_required_edge_labels": 0,
                "grouped_nodes": 2,
                "group_labelled_nodes": 1,
                "visible_group_boundaries": 2,
                "group_boundary_overlap_count": 1,
            },
        },
    )

    assert review["approved"] is False
    assert review["terminal"] is True
    assert any("overview-required edge label" in item for item in review["missing"])
    assert any("group label on every node" in item for item in review["missing"])
    assert any("responsibility-zone boundaries" in item for item in review["missing"])


def test_render_gate_accepts_legacy_reports_without_new_visual_metrics():
    graph = {"nodes": [{"id": "a"}], "edges": []}
    review = _deterministic_render_review(
        graph,
        {
            "screenshot_base64": "legacy-image",
            "report": {
                "rendered_nodes": 1,
                "rendered_edges": 0,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 11,
            },
        },
    )

    assert review["approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_count", "expected_effort"),
    [(0, "medium"), (1, "medium")],
)
async def test_semantic_critic_reviews_the_private_rendered_image(
    monkeypatch,
    revision_count,
    expected_effort,
):
    captured = {}
    architect_tail = "a" * 10_100 + " architect-tail"
    challenger_tail = "c" * 6_100 + " challenger-tail"

    async def fake_stream_llm(**kwargs):
        captured.update(kwargs)
        return _structured_response(_passing_review_payload())

    async def send(_event):
        return None

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render-image",
            "media_type": "image/png",
            "report": {
                "rendered_nodes": 6,
                "rendered_edges": 1,
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    graph["design_origin"] = "applied"
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "Design a production growth marketing agent system",
            "evidence_bundle": {
                "checklist": [{"area": "evaluation", "question": "Measure outcomes"}],
                "book_evidence": [
                    {
                        "chapter": 1,
                        "page_number": 8,
                        "text": "Evaluate measured outcomes.",
                    }
                ],
                "research_context": "- [Current source](https://example.com): current evidence",
            },
            "architect_plan": {
                "diagram_requirements": [architect_tail],
                "runtime_flow": ["full-plan-duplicate-must-not-ship"],
            },
            "challenger_review": {
                "risks": [
                    {
                        "area": "safety",
                        "risk": "Unapproved writes",
                        "mitigation": "Approval gate",
                    },
                    {
                        "area": "completeness",
                        "risk": challenger_tail,
                        "mitigation": "Keep it visible",
                    },
                ],
                "status_update": "challenger-status-must-not-ship",
            },
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
            "graph_revision_count": revision_count,
        }
    )

    assert result["graph_review"]["approved"] is True
    assert captured["effort"] == expected_effort
    assert captured["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    content = captured["messages"][0]["content"]
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "private-render-image",
        },
    }
    packet = json.loads(content[0]["text"].split("\n", 1)[1])
    assert packet["render_report"]["rendered_nodes"] == 6
    assert "https://example.com" in packet["evidence_allowlist"]
    assert packet["review_context"] == [
        f"Architect commitment: {architect_tail}",
        "Challenger risk (safety): Unapproved writes Mitigation: Approval gate",
        f"Challenger risk (completeness): {challenger_tail} Mitigation: Keep it visible",
    ]
    assert "full-plan-duplicate-must-not-ship" not in content[0]["text"]
    assert "challenger-status-must-not-ship" not in content[0]["text"]
    assert "Judge its visual hierarchy" in _GRAPH_CRITIC_SYSTEM


def test_review_packet_keeps_semantics_and_omits_duplicate_internal_metadata():
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"], start=1):
        node["id"] = f"node-{index}"
    graph.update(
        {
            "version": "private-version",
            "resolved_complexity": "production",
            "groups": [
                {
                    "id": "runtime",
                    "label": "Runtime",
                    "kind": "runtime",
                    "nodeIds": [node["id"] for node in graph["nodes"]],
                }
            ],
            "sequence": [
                {
                    "step": 1,
                    "nodes": [graph["nodes"][0]["id"]],
                    "description": "Enter the runtime path",
                }
            ],
            "assumptions": ["The campaign API supports exact-action approval."],
        }
    )
    graph["nodes"][0].update(
        {
            "technology": "Internal presentation subtitle",
            "detail": "Deferred detail",
            "layer": "architecture",
            "design_origin": "applied",
        }
    )
    graph["edges"][0].update(
        {
            "technology": "Internal edge subtitle",
            "description": graph["edges"][0]["label"],
            "edge_id": "private-edge-id",
            "relation": "private-relation",
        }
    )
    packet = _review_packet(
        {
            "architect_plan": {
                "diagram_requirements": ["Bind approval to the exact action."],
                "runtime_flow": ["Duplicate planning prose"],
            },
            "challenger_review": {
                "risks": [
                    {
                        "area": "safety",
                        "risk": "Approval can go stale.",
                        "mitigation": "Revalidate immediately before execution.",
                    }
                ],
                "missing_requirements": ["Confirm the source of truth."],
                "tradeoffs": ["Freshness adds one read."],
                "status_update": "Duplicate progress prose",
            },
        },
        graph=graph,
        query="Design the system.",
        resolved_depth="production",
        render_result={
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "unknown_browser_field": "omit",
            },
        },
    )

    assert packet["review_context"] == [
        "Architect commitment: Bind approval to the exact action.",
        "Challenger risk (safety): Approval can go stale. Mitigation: Revalidate immediately before execution.",
        "Challenger missing requirement: Confirm the source of truth.",
        "Challenger tradeoff: Freshness adds one read.",
    ]
    candidate = packet["candidate"]
    assert len(candidate["nodes"]) == len(graph["nodes"])
    assert len(candidate["edges"]) == len(graph["edges"])
    assert candidate["nodes"][0]["description"] == graph["nodes"][0]["description"]
    assert set(candidate["nodes"][0]) <= {
        "id",
        "label",
        "type",
        "description",
    }
    assert set(candidate["edges"][0]) <= {
        "source",
        "target",
        "label",
        "flow",
        "sync",
    }
    assert candidate["groups"] == graph["groups"]
    assert candidate["sequence"] == graph["sequence"]
    assert candidate["assumptions"] == graph["assumptions"]
    assert packet["render_report"] == {
        "rendered_nodes": len(graph["nodes"]),
        "rendered_edges": len(graph["edges"]),
    }
    packet_text = json.dumps(packet)
    assert "private-version" not in packet_text
    assert "private-edge-id" not in packet_text
    assert "Duplicate planning prose" not in packet_text
    assert "Duplicate progress prose" not in packet_text


@pytest.mark.asyncio
async def test_terse_followup_still_reviews_every_changed_applied_graph(monkeypatch):
    calls = {"critic": 0, "render": 0}

    async def fake_stream_llm(**_kwargs):
        calls["critic"] += 1
        return _structured_response(
            _passing_review_payload(
                strengths=["The requested approval path remains domain specific."],
            )
        )

    async def await_diagram(graph):
        calls["render"] += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "expand the approval path",
            "design_query": "growth marketing multi-agent system expand the approval path",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is True
    assert calls == {"critic": 1, "render": 1}


@pytest.mark.asyncio
async def test_hard_render_failure_skips_the_paid_semantic_critic(monkeypatch):
    async def fail_stream_llm(**_kwargs):
        raise AssertionError("hard deterministic failures must not spend a critic call")

    async def await_diagram(_graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": 5,
                "rendered_edges": 1,
                "overlap_count": 1,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fail_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert any("overlapping" in item for item in result["graph_review"]["missing"])
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["review_status"] == "completed"
    assert "repair_contract" not in result["graph_review"]
    assert (
        result["graph_review"]["failure_code"] == "diagram_evaluation_layout_rejected"
    )


@pytest.mark.asyncio
async def test_missing_browser_evaluation_fails_closed_before_paid_semantic_review(
    monkeypatch,
):
    calls = 0

    async def fake_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(_graph):
        raise TimeoutError("browser did not respond")

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert calls == 0
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "diagram_evaluation_timeout"


@pytest.mark.asyncio
async def test_deterministic_domain_findings_reach_semantic_localization(monkeypatch):
    calls = []
    finding = (
        "Replace generic book concepts with domain-owned component responsibilities."
    )

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        payload = _passing_review_payload()
        payload["repair_scope"] = "local"
        _set_model_layer(
            payload,
            "components",
            status="fail",
            score=0.7,
            finding_codes=[1],
            deterministic_finding_indexes=[0],
            node_indexes=[0],
        )
        return _structured_response(payload)

    async def await_diagram(candidate):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(candidate["nodes"]),
                "rendered_edges": len(candidate["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    graph = _domain_graph()
    for index, node in enumerate(graph["nodes"]):
        node["id"] = f"growth_stage_{index}"
    graph["edges"] = [
        {
            "source": f"growth_stage_{index}",
            "target": f"growth_stage_{index + 1}",
            "label": f"passes campaign state {index}",
        }
        for index in range(len(graph["nodes"]) - 1)
    ]
    graph["nodes"][0]["label"] = "Agent"
    result = await graph_critic_node(
        {
            "graph_data": graph,
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["repair_contract"]["repair_scope"] == "local"
    packet = json.loads(calls[0]["messages"][0]["content"][0]["text"].split("\n", 1)[1])
    assert packet["deterministic_pre_review_findings"] == [
        {
            "id": "deterministic_1",
            "finding": finding,
            "owner_layer": "components",
        }
    ]


@pytest.mark.asyncio
async def test_malformed_structured_review_fails_closed_without_retry(monkeypatch):
    calls = []
    render_calls = 0

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response('{"approved": tru')

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_output_truncated"
    assert len(calls) == 1
    assert calls[0]["model"] == settings.graph_qa_model
    assert calls[0]["timeout_seconds"] <= settings.graph_critic_max_timeout_s
    assert calls[0]["max_output_tokens"] == settings.graph_qa_max_completion_tokens
    assert calls[0]["effort"] == "medium"
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert render_calls == 1


@pytest.mark.asyncio
async def test_browser_render_time_is_deducted_from_one_absolute_critic_deadline(
    monkeypatch,
):
    clock = {"now": 100.0}
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(graph):
        clock["now"] += 7.0
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(event):
        events.append(event)

    monkeypatch.setattr("agent.nodes.graph_critic.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
            "_graph_stage_deadline_s": 145.0,
        }
    )

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert calls[0]["timeout_seconds"] == pytest.approx(37.0)
    assert any(
        event.get("phase") == "review" and event.get("status") == "complete"
        for event in events
    )


@pytest.mark.asyncio
async def test_prototype_critic_uses_depth_specific_wire_contract(monkeypatch):
    calls = []
    payload = _passing_review_payload(topology_proofs={})

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(payload)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(_critic_state())

    assert result["graph_review"]["approved"] is True
    assert result["graph_review"]["topology_proofs"] == []
    assert len(calls) == 1
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert calls[0]["response_schema"]["properties"]["topology_proofs"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    assert '"topology_proofs": {}' in calls[0]["system"]
    assert "state_effect_reconciliation" not in calls[0]["system"]
    assert "topology guarantee" not in calls[0]["system"]
    assert "topology-proof contracts" not in calls[0]["system"]
    assert "Preserve every required layer and proof" not in calls[0]["system"]


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_protocol_correction_logs_safe_coordinates(
    monkeypatch,
    caplog,
    recovers,
):
    invalid = _passing_review_payload()
    _set_model_layer(invalid, "components", status="PRIVATE_SENTINEL")
    valid = _passing_review_payload()
    calls = []
    events = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        response = valid if recovers and len(calls) == 2 else invalid
        return _structured_response(response)

    async def send(event):
        events.append(event)

    caplog.set_level("WARNING", logger="agent.nodes.graph_critic")
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    state = _critic_state()
    state["send"] = send
    result = await graph_critic_node(state)

    assert result["graph_review"]["approved"] is recovers
    assert len(calls) == 2
    assert "path=layers.components.status" in caplog.text
    assert "rule=invalid_enum" in caplog.text
    assert "PRIVATE_SENTINEL" not in caplog.text
    if not recovers:
        assert result["graph_review"]["terminal"] is True
        terminal_logs = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Model review unavailable")
        ]
        assert len(terminal_logs) == 1
        assert (
            "path=layers.components.status rule=invalid_enum" in terminal_logs[0]
        )
        assert (
            result["graph_review"]["failure_code"]
            == "semantic_review_protocol_invalid"
        )
        review_event = events[-1]
        assert review_event["validation_stage"] == "correction"
        assert review_event["validation_path"] == "layers.components.status"
        assert review_event["validation_rule"] == "invalid_enum"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_payload",
    [
        {
            "repair_contract": {"repair_scope": "none", "layers": {}},
            "strengths": ["The runtime path is explicit."],
            "advice": [],
            "topology_proofs": [],
        },
        {
            "strengths": ["The runtime path is explicit."],
            "advice": [],
            "topology_proofs": [],
        },
    ],
)
async def test_invalid_structured_review_contract_fails_closed(
    monkeypatch,
    invalid_payload,
):
    calls = []
    render_calls = 0

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(invalid_payload)

    async def await_diagram(graph):
        nonlocal render_calls
        render_calls += 1
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_protocol_invalid"
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "repair_contract" not in result["graph_review"]
    assert len(calls) == 2
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_PROTOTYPE_RESPONSE_SCHEMA
    assert "state_effect_reconciliation" not in calls[0]["system"]
    assert calls[1]["effort"] == "medium"
    assert "topology guarantee" not in calls[1]["system"]
    correction_text = calls[1]["messages"][0]["content"][-1]["text"]
    assert "topology-proof contracts" not in correction_text
    assert calls[1]["telemetry"]["operation"] == "graph_critic_protocol_correction"
    assert render_calls == 1


def _valid_protocol_topology_proofs(edge=None):
    edge = edge or {
        "source": "source_node",
        "target": "target_node",
        "label": "carries typed payload",
    }
    return [
        {
            "guarantee": guarantee,
            "status": "pass",
            "edge_evidence": [edge],
            "route_claims": [{"source": edge["source"], "target": edge["target"]}],
            "reason": "The cited witness subgraph supports this guarantee.",
        }
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    ]


def _valid_model_topology_proofs():
    return {
        guarantee: ["pass", [0], [[0, 1]]]
        for guarantee in sorted(_TOPOLOGY_PROOF_GUARANTEES)
    }


def _protocol_review(topology_proofs):
    return {
        "repair_contract": _repair_contract(),
        "strengths": ["The runtime path is explicit."],
        "advice": [],
        "topology_proofs": topology_proofs,
    }


@pytest.mark.parametrize(
    "defect",
    [
        "missing_proof",
        "duplicate_guarantee",
        "invalid_status",
        "invalid_evidence",
        "empty_pass_evidence",
        "invalid_reason",
    ],
)
def test_production_critic_protocol_rejects_malformed_topology_proofs(defect):
    proofs = _valid_protocol_topology_proofs()
    if defect == "missing_proof":
        proofs.pop()
    elif defect == "duplicate_guarantee":
        proofs[-1]["guarantee"] = proofs[0]["guarantee"]
    elif defect == "invalid_status":
        proofs[0]["status"] = "approved"
    elif defect == "invalid_evidence":
        proofs[0]["edge_evidence"] = [{"source": "source_node"}]
    elif defect == "empty_pass_evidence":
        proofs[0]["edge_evidence"] = []
    else:
        proofs[0]["reason"] = ["not", "a", "string"]

    with pytest.raises(ValueError, match="critic response protocol invalid"):
        _validate_review_protocol(
            _protocol_review(proofs),
            require_topology_proofs=True,
        )


def test_production_critic_protocol_accepts_complete_topology_proofs():
    _validate_review_protocol(
        _protocol_review(_valid_protocol_topology_proofs()),
        require_topology_proofs=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_malformed_topology_proofs_get_one_bounded_correction(
    monkeypatch,
    caplog,
    recovers,
):
    graph = {
        "design_origin": "applied",
        "nodes": [
            {"id": "source_node", "label": "Source"},
            {"id": "target_node", "label": "Target"},
        ],
        "edges": [
            {
                "source": "source_node",
                "target": "target_node",
                "label": "carries typed payload",
            }
        ],
        "groups": [],
        "sequence": [],
        "assumptions": [],
    }
    valid = _passing_review_payload(
        topology_proofs=_valid_model_topology_proofs()
    )
    malformed = deepcopy(valid)
    malformed_guarantee = sorted(_TOPOLOGY_PROOF_GUARANTEES)[0]
    malformed["topology_proofs"][malformed_guarantee] = ["pass", [], []]
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        response = valid if recovers and len(calls) == 2 else malformed
        return _structured_response(response)

    caplog.set_level("WARNING", logger="agent.nodes.graph_critic")
    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    monkeypatch.setattr(
        "agent.nodes.graph_critic._deterministic_review",
        lambda *_args, **_kwargs: {
            "approved": True,
            "score": 1.0,
            "strengths": [],
            "missing": [],
            "advice": [],
            "revision_instruction": "",
        },
    )
    result = await graph_critic_node(
        _critic_state(graph=graph, complexity="production")
    )

    assert result["graph_review"]["approved"] is recovers
    assert result["graph_review"]["review_status"] == (
        "completed" if recovers else "unavailable"
    )
    if recovers:
        assert len(result["graph_review"]["topology_proofs"]) == len(
            _TOPOLOGY_PROOF_GUARANTEES
        )
    else:
        assert result["graph_review"]["terminal"] is True
        assert (
            result["graph_review"]["failure_code"]
            == "semantic_review_protocol_invalid"
        )
    assert len(calls) == 2
    assert calls[0]["response_schema"] == _GRAPH_CRITIC_RESPONSE_SCHEMA
    assert "state_effect_reconciliation" in calls[0]["system"]
    assert "Preserve every required proof" in calls[0]["system"]
    assert calls[1]["effort"] == "medium"
    correction_text = calls[1]["messages"][0]["content"][-1]["text"]
    assert "topology-proof contracts" in correction_text
    assert f"path=topology_proofs.{malformed_guarantee}" in caplog.text
    assert "rule=missing_evidence" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "failure_code", "call_count"),
    [
        ("max_tokens", "semantic_review_output_truncated", 1),
        (None, "semantic_review_protocol_invalid", 2),
    ],
)
async def test_incomplete_structured_review_fails_closed_without_retry(
    monkeypatch,
    finish_reason,
    failure_code,
    call_count,
):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            ),
            finish_reason=finish_reason,
        )

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert len(calls) == call_count
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == failure_code
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "missing" not in result["graph_review"]


@pytest.mark.asyncio
async def test_valid_first_semantic_review_uses_one_call(monkeypatch):
    calls = []

    async def fake_stream_llm(**kwargs):
        calls.append(kwargs)
        return _structured_response(
            _passing_review_payload(
                strengths=["The runtime path is explicit."],
            )
        )

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(_event):
        return None

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fake_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert result["graph_review"]["approved"] is True
    assert len(calls) == 1
    assert "semantic_attempt" not in calls[0]["telemetry"]["metadata"]


def test_semantic_review_wire_has_only_fixed_scorecard_fields():
    assert set(_GRAPH_CRITIC_RESPONSE_SCHEMA["properties"]) == {
        "repair_scope",
        "layers",
        "topology_proofs",
    }
    schema_text = json.dumps(_GRAPH_CRITIC_RESPONSE_SCHEMA)
    assert "blocking_findings" not in schema_text
    assert '"reason"' not in schema_text
    assert '"strengths"' not in schema_text
    assert '"advice"' not in schema_text


def test_semantic_review_failure_classifies_truncated_protocol_output():
    from agent.nodes.graph_critic import _semantic_review_failure_code

    assert (
        _semantic_review_failure_code(
            ValueError("invalid JSON"),
            '{"approved":false',
        )
        == "semantic_review_output_truncated"
    )
    assert (
        _semantic_review_failure_code(
            TimeoutError("provider unavailable"),
            "",
        )
        == "semantic_review_timeout"
    )


@pytest.mark.asyncio
async def test_semantic_critic_outage_fails_closed(monkeypatch):
    calls = 0
    events = []

    async def fail_stream_llm(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("provider unavailable")

    async def await_diagram(graph):
        return {
            "screenshot_base64": "private-render",
            "report": {
                "rendered_nodes": len(graph["nodes"]),
                "rendered_edges": len(graph["edges"]),
                "overlap_count": 0,
                "clipped_nodes": 0,
                "clipped_edges": 0,
                "minimum_text_px": 12,
            },
        }

    async def send(event):
        events.append(event)

    monkeypatch.setattr(
        "agent.nodes.graph_critic.stream_structured_llm",
        fail_stream_llm,
    )
    result = await graph_critic_node(
        {
            "graph_data": _domain_graph(),
            "graph_changed": True,
            "user_message": "growth marketing multi-agent system",
            "complexity": "prototype",
            "send": send,
            "await_diagram_evaluation": await_diagram,
            "user_id": "user-1",
            "session_id": "thread-1",
        }
    )

    assert calls == 1
    assert result["graph_review"]["approved"] is False
    assert result["graph_review"]["terminal"] is True
    assert result["graph_review"]["failure_code"] == "semantic_review_timeout"
    assert any(
        event.get("failure_code") == "semantic_review_timeout" for event in events
    )
    assert result["graph_review"]["review_status"] == "unavailable"
    assert "missing" not in result["graph_review"]
